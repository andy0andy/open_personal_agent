import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ThreadSearchResults } from "./ThreadSearchResults";
import { MoreHorizontal, PanelLeftClose, Plus, Search } from "lucide-react";
import { useCallback, useEffect, useState, type DragEvent } from "react";
import { api, readableError } from "../../api/client";
import { threadsQuery } from "../../api/queries";
import type { Thread } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { closesOverlay } from "../../components/ui/escape";
import { StatusDot } from "../../components/ui/StatusDot";
import { filterThreads, relativeTime, threadActivity, type ThreadActivityView } from "./activity";
import { useArchive } from "./archive";
import { ArchivedThreads } from "./ArchivedThreads";
import { addCreatedThread, forgetThread, replaceThread } from "./cache";
import { DeleteThreadDialog } from "./DeleteThreadDialog";
import { isImeComposing } from "../../components/ime";
import { moveItem, pendingOrder, sameOrder } from "./order";
import { reorderMutation } from "./reorder";
import { ThreadMenu, type MenuPosition } from "./ThreadMenu";

interface DropTarget {
  threadId: string;
  place: "before" | "after";
}

// 行右侧的状态字：待审批要你处理，用正文色；出错用危险色；有新回答用成功色
const META_TONE: Record<ThreadActivityView["tone"], string> = {
  warning: "text-foreground",
  info: "text-muted-foreground",
  danger: "text-danger",
  success: "text-success",
};

/** 侧栏的操作失败提示几秒后自动消失，不一直挂着（之后的操作成功与否与它无关）。 */
function useAutoReset(mutation: { isError: boolean; reset: () => void }, delay = 5000) {
  const { isError, reset } = mutation;
  useEffect(() => {
    if (!isError) return;
    const timer = setTimeout(reset, delay);
    return () => clearTimeout(timer);
  }, [isError, reset, delay]);
}

/**
 * 对话页第二栏的会话列表（设计 2026-10-22 3.1）：每行 = 状态点 + 标题 + 状态字或相对时间；
 * 顶部搜索标题与内容（设计 2026-10-23 6.1）；自定义顺序（拖拽调整，搜索时不能拖：过滤后的顺序不能写回）；
 * 悬停"⋯"或右键打开菜单、原地重命名。传了 onCollapse 时顶部多一个收起按钮。
 */
export function ThreadList({
  selectedId,
  onSelect,
  onCollapse,
}: {
  selectedId: string | null;
  onSelect: (threadId: string) => void;
  onCollapse?: () => void;
}) {
  const queryClient = useQueryClient();
  const threads = useQuery(threadsQuery);
  const [menu, setMenu] = useState<MenuPosition | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteFrom, setDeleteFrom] = useState<HTMLElement | null>(null); // 关掉删除框后焦点回到它
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [drop, setDrop] = useState<DropTarget | null>(null);
  const [query, setQuery] = useState("");
  const closeMenu = useCallback(() => setMenu(null), []);

  const create = useMutation({
    mutationFn: api.createThread,
    onSuccess: async (thread) => {
      await addCreatedThread(queryClient, thread);
      onSelect(thread.id);
    },
  });
  const archive = useArchive();
  const rename = useMutation({
    mutationFn: ({ threadId, title }: { threadId: string; title: string }) =>
      api.updateThread(threadId, { title }),
    onSuccess: (thread) => replaceThread(queryClient, thread),
  });
  const remove = useMutation({
    mutationFn: api.deleteThread,
    onSuccess: (_, threadId) => {
      setDeletingId(null);
      // 从列表移除；若正打开这个会话，右侧随之回到 /chat 的新会话页
      forgetThread(queryClient, threadId);
    },
  });
  const closeDeleteDialog = useCallback(() => {
    setDeletingId(null);
    remove.reset();
  }, [remove]);
  const reorder = useMutation(reorderMutation(queryClient));
  useAutoReset(create);
  useAutoReset(rename);
  useAutoReset(reorder);

  // 拖动排序保存中：按正在保存的顺序显示，轮询带回的旧顺序不把界面翻回去（积压小问题 B1）
  const list =
    reorder.isPending && reorder.variables
      ? pendingOrder(threads.data ?? [], reorder.variables)
      : (threads.data ?? []);
  const filtering = query.trim() !== "";
  const shown = filterThreads(list, query);
  const now = new Date();

  const finishDrag = () => {
    const current = list.map((thread) => thread.id);
    const ids = draggingId && drop ? moveItem(current, draggingId, drop.threadId, drop.place) : [];
    if (ids.length > 0 && !sameOrder(ids, current)) {
      const byId = new Map(list.map((thread) => [thread.id, thread]));
      // 先在界面上排好，再保存到服务器
      queryClient.setQueryData<Thread[]>(
        threadsQuery.queryKey,
        ids.flatMap((id) => byId.get(id) ?? []),
      );
      reorder.mutate(ids);
    }
    setDraggingId(null);
    setDrop(null);
  };

  const dragOver = (event: DragEvent<HTMLLIElement>, threadId: string) => {
    if (!draggingId) return;
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const place = event.clientY < rect.top + rect.height / 2 ? "before" : "after";
    if (drop?.threadId !== threadId || drop.place !== place) setDrop({ threadId, place });
  };

  const commitRename = (thread: Thread, value: string) => {
    setRenamingId(null);
    const title = value.trim();
    if (title && title !== thread.title) rename.mutate({ threadId: thread.id, title });
  };

  return (
    <nav aria-label="会话列表" className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex items-center justify-between gap-2 pl-1.5">
        <span className="text-[13px] font-medium text-muted-foreground">会话</span>
        <div className="flex items-center gap-1">
          <Button
            aria-label="新建会话"
            title="新建会话"
            disabled={create.isPending}
            onClick={() => create.mutate()}
          >
            <Plus className="size-3.5" aria-hidden="true" />
            新建
          </Button>
          {onCollapse && (
            <button
              type="button"
              aria-label="收起会话列表"
              title="收起会话列表"
              className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              onClick={onCollapse}
            >
              <PanelLeftClose className="size-4" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>
      {/* 聚焦框画在外框上（与输入框的全局焦点框一样），所以输入框自己不画 */}
      <label className="flex h-[34px] items-center gap-2 rounded-lg border border-input px-2.5 text-muted-foreground focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ring">
        <Search className="size-3.5 shrink-0" aria-hidden="true" />
        <input
          type="search"
          aria-label="搜索会话"
          placeholder="搜索会话标题与内容"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (closesOverlay(event.nativeEvent)) setQuery("");
          }}
          className="min-w-0 flex-1 bg-transparent text-[13px] text-foreground outline-none placeholder:text-muted-foreground"
        />
      </label>
      {create.isError && (
        <p className="px-2 text-xs text-danger">新建会话失败：{readableError(create.error)}</p>
      )}
      {rename.isError && (
        <p className="px-2 text-xs text-danger">重命名失败：{readableError(rename.error)}</p>
      )}
      {reorder.isError && (
        <p className="px-2 text-xs text-danger">保存顺序失败：{readableError(reorder.error)}</p>
      )}
      {threads.isError && <p className="px-2 text-xs text-danger">会话列表加载失败，正在重试…</p>}
      {filtering && (
        <p className="px-2 text-xs font-medium text-muted-foreground">
          {shown.length === 0 ? `没有标题含“${query.trim()}”的会话` : "标题匹配"}
        </p>
      )}
      <ul
        className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto"
        onDragOver={(event) => {
          // 只处理列表下方的空白处（落在某一行上时由该行处理）：放下即移到最后
          const last = list.at(-1);
          if (!draggingId || !last || event.target !== event.currentTarget) return;
          event.preventDefault();
          if (drop?.threadId !== last.id || drop.place !== "after") {
            setDrop({ threadId: last.id, place: "after" });
          }
        }}
        onDrop={(event) => {
          if (event.target !== event.currentTarget) return;
          event.preventDefault();
          finishDrag();
        }}
      >
        {shown.map((thread) => {
          const selected = thread.id === selectedId;
          const activity = threadActivity(thread);
          const dropLine =
            drop?.threadId === thread.id && draggingId !== thread.id
              ? drop.place === "before"
                ? "border-t-2 border-primary"
                : "border-b-2 border-primary"
              : "border-y-2 border-transparent";
          return (
            <li
              key={thread.id}
              draggable={!filtering && renamingId !== thread.id}
              onDragStart={(event) => {
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", thread.id);
                setDraggingId(thread.id);
              }}
              onDragOver={(event) => dragOver(event, thread.id)}
              onDrop={(event) => {
                event.preventDefault();
                finishDrag();
              }}
              onDragEnd={() => {
                setDraggingId(null);
                setDrop(null);
              }}
              onContextMenu={(event) => {
                if (renamingId === thread.id) return; // 正在重命名：保留输入框自己的右键菜单（粘贴等）
                event.preventDefault();
                setMenu({
                  threadId: thread.id,
                  x: event.clientX,
                  y: event.clientY,
                  trigger: event.currentTarget.querySelector<HTMLElement>('[role="button"]'),
                });
              }}
              className={`group relative ${dropLine} ${draggingId === thread.id ? "opacity-50" : ""}`}
            >
              {renamingId === thread.id ? (
                <input
                  autoFocus
                  aria-label="会话名称"
                  defaultValue={thread.title}
                  maxLength={100}
                  className="w-full rounded-lg border border-ring bg-card px-2 py-1 text-sm text-foreground outline-none"
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !isImeComposing(event.nativeEvent)) {
                      commitRename(thread, event.currentTarget.value);
                    }
                    if (closesOverlay(event.nativeEvent)) setRenamingId(null);
                  }}
                  onBlur={(event) => commitRename(thread, event.currentTarget.value)}
                />
              ) : (
                // 用可聚焦的 div 而不是按钮：按钮作为原生拖动的起点在 Firefox / Safari 上不可靠
                <div
                  role="button"
                  tabIndex={0}
                  // 焦点框往里画：列表会滚动，往外画会被裁掉
                  className={`flex w-full cursor-pointer items-center gap-2.5 rounded-lg py-2 pr-2 pl-2.5 text-left text-sm transition-colors select-none focus-visible:-outline-offset-2 ${
                    selected
                      ? "bg-accent text-foreground"
                      : activity
                        ? "text-foreground hover:bg-muted"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  }`}
                  onClick={() => onSelect(thread.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect(thread.id);
                    }
                  }}
                >
                  {activity ? (
                    <StatusDot tone={activity.tone} pulse={activity.pulse} />
                  ) : (
                    <span aria-hidden="true" className="size-2 shrink-0" />
                  )}
                  <span className="min-w-0 flex-1 truncate">{thread.title || "新会话"}</span>
                  {/* 悬停或聚焦时让位给"⋯"按钮；状态仍由圆点表示 */}
                  <span
                    className={`shrink-0 text-xs tabular-nums transition-opacity group-focus-within:opacity-0 group-hover:opacity-0 ${
                      activity ? META_TONE[activity.tone] : "text-muted-foreground"
                    }`}
                  >
                    {activity?.label ?? relativeTime(thread.updated_at, now)}
                  </span>
                </div>
              )}
              {renamingId !== thread.id && (
                <button
                  aria-label="更多操作"
                  aria-haspopup="menu"
                  aria-expanded={menu?.threadId === thread.id}
                  className="absolute top-1/2 right-1 -translate-y-1/2 rounded-md p-1 text-muted-foreground opacity-0 group-focus-within:opacity-100 group-hover:opacity-100 hover:bg-muted hover:text-foreground focus:opacity-100"
                  // 菜单打开时再点"⋯"是收起：不让菜单的"点外面关闭"先关掉、点击又重新打开
                  onMouseDown={(event) => {
                    if (menu?.threadId === thread.id) event.stopPropagation();
                  }}
                  onClick={(event) => {
                    if (menu?.threadId === thread.id) return setMenu(null);
                    const rect = event.currentTarget.getBoundingClientRect();
                    setMenu({
                      threadId: thread.id,
                      x: rect.left,
                      y: rect.bottom + 4,
                      trigger: event.currentTarget,
                    });
                  }}
                >
                  <MoreHorizontal className="size-3.5" aria-hidden="true" />
                </button>
              )}
            </li>
          );
        })}
        {filtering && (
          <li>
            <ThreadSearchResults query={query} shown={shown} />
          </li>
        )}
      </ul>
      <ArchivedThreads selectedId={selectedId} onSelect={onSelect} />
      {menu && (
        <ThreadMenu
          position={menu}
          onClose={closeMenu}
          onArchive={(threadId, archived) => {
            setMenu(null);
            archive.mutate({ threadId, archived });
          }}
          onRename={(threadId) => {
            setMenu(null);
            setRenamingId(threadId);
          }}
          onDelete={(threadId) => {
            setDeleteFrom(menu.trigger);
            setMenu(null);
            remove.reset();
            setDeletingId(threadId);
          }}
        />
      )}
      {deletingId && (
        <DeleteThreadDialog
          title={list.find((thread) => thread.id === deletingId)?.title || "新会话"}
          pending={remove.isPending}
          error={remove.error}
          onConfirm={() => remove.mutate(deletingId)}
          onCancel={closeDeleteDialog}
          returnFocus={deleteFrom}
        />
      )}
    </nav>
  );
}
