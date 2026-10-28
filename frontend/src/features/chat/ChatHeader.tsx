import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, MoreHorizontal } from "lucide-react";
import { useCallback, useState } from "react";
import { api, exportUrl, readableError } from "../../api/client";
import type { Thread } from "../../api/types";
import { isImeComposing } from "../../components/ime";
import { Button } from "../../components/ui/Button";
import { closesOverlay } from "../../components/ui/escape";
import { useArchive } from "../threads/archive";
import { forgetThread, replaceThread } from "../threads/cache";
import { DeleteThreadDialog } from "../threads/DeleteThreadDialog";
import { ThreadMenu, type MenuPosition } from "../threads/ThreadMenu";

/**
 * 对话区顶栏（设计 2026-10-22 3.2）：标题 + 一行"N 轮"；右边"文件"（从输入框工具条挪来）
 * 与"更多"（改名、删除，沿用会话列表的菜单）。权限与模型留在输入框工具条，这里不重复。
 */
export function ChatHeader({
  thread,
  rounds,
  filesOpen,
  onToggleFiles,
}: {
  thread: Thread;
  /** 用户发过几条消息 */
  rounds: number;
  filesOpen: boolean;
  onToggleFiles: () => void;
}) {
  const queryClient = useQueryClient();
  const [menu, setMenu] = useState<MenuPosition | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteFrom, setDeleteFrom] = useState<HTMLElement | null>(null); // 关掉删除框后焦点回到它
  const closeMenu = useCallback(() => setMenu(null), []);

  const archive = useArchive();
  const rename = useMutation({
    mutationFn: (title: string) => api.updateThread(thread.id, { title }),
    onSuccess: (updated) => replaceThread(queryClient, updated),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteThread(thread.id),
    onSuccess: () => {
      setDeleting(false);
      // 对话页发现会话不在了（列表里没有、按 ID 也取不到），随之回到 /chat
      forgetThread(queryClient, thread.id);
    },
  });
  const closeDeleteDialog = useCallback(() => {
    setDeleting(false);
    remove.reset();
  }, [remove]);

  const commitRename = (value: string) => {
    setRenaming(false);
    const title = value.trim();
    if (title && title !== thread.title) rename.mutate(title);
  };

  const title = thread.title || "新会话";
  return (
    <header className="flex h-15 shrink-0 items-center gap-2.5 border-b border-border px-6">
      <div className="min-w-0 flex-1">
        {renaming ? (
          <input
            autoFocus
            aria-label="会话名称"
            defaultValue={thread.title}
            maxLength={100}
            className="w-full rounded-lg border border-input bg-background px-2 text-[17px] leading-tight font-semibold"
            onKeyDown={(event) => {
              if (event.key === "Enter" && !isImeComposing(event.nativeEvent)) {
                commitRename(event.currentTarget.value);
              }
              if (closesOverlay(event.nativeEvent)) setRenaming(false);
            }}
            onBlur={(event) => commitRename(event.currentTarget.value)}
          />
        ) : (
          <h1 className="truncate text-[17px] leading-tight font-semibold" title={title}>
            {title}
          </h1>
        )}
        {rename.isError ? (
          <p className="truncate text-xs text-danger">改名失败：{readableError(rename.error)}</p>
        ) : (
          <p className="truncate text-xs text-muted-foreground">
            {rounds > 0 ? `${rounds} 轮` : "还没有对话"}
          </p>
        )}
      </div>
      <Button aria-pressed={filesOpen} onClick={onToggleFiles} className="aria-pressed:bg-accent">
        <FolderOpen className="size-4" aria-hidden="true" />
        文件
      </Button>
      <button
        type="button"
        aria-label="更多操作"
        title="更多：改名、删除"
        aria-haspopup="menu"
        aria-expanded={menu !== null}
        className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
        // 菜单打开时再点是收起：不让菜单的"点外面关闭"先关掉、点击又重新打开
        onMouseDown={(event) => {
          if (menu) event.stopPropagation();
        }}
        onClick={(event) => {
          if (menu) return setMenu(null);
          const rect = event.currentTarget.getBoundingClientRect();
          setMenu({
            threadId: thread.id,
            x: rect.right,
            y: rect.bottom + 4,
            trigger: event.currentTarget,
          });
        }}
      >
        <MoreHorizontal className="size-4" aria-hidden="true" />
      </button>
      {menu && (
        <ThreadMenu
          position={menu}
          onClose={closeMenu}
          archived={thread.archived}
          onArchive={(threadId, archived) => {
            setMenu(null);
            archive.mutate({ threadId, archived });
          }}
          onExport={(threadId) => {
            setMenu(null);
            // 下载靠响应的 Content-Disposition，不离开页面
            const link = document.createElement("a");
            link.href = exportUrl(threadId, Intl.DateTimeFormat().resolvedOptions().timeZone);
            link.click();
          }}
          onRename={() => {
            setMenu(null);
            rename.reset();
            setRenaming(true);
          }}
          onDelete={() => {
            setDeleteFrom(menu.trigger);
            setMenu(null);
            remove.reset();
            setDeleting(true);
          }}
        />
      )}
      {deleting && (
        <DeleteThreadDialog
          title={title}
          pending={remove.isPending}
          error={remove.error}
          onConfirm={() => remove.mutate()}
          onCancel={closeDeleteDialog}
          returnFocus={deleteFrom}
        />
      )}
    </header>
  );
}
