import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Sparkles } from "lucide-react";
import { useId, useState } from "react";
import { useNavigate } from "react-router";
import { api, readableError } from "../../api/client";
import { modelsAdminQuery, threadsQuery } from "../../api/queries";
import type { PermissionMode } from "../../api/types";
import { isImeComposing } from "../../components/ime";
import { StatusDot } from "../../components/ui/StatusDot";
import { chatPath } from "../../layout/routes";
import { ModelSelect } from "../models/ModelSelect";
import { relativeTime, threadActivity } from "../threads/activity";
import { rememberNewThread, startNewChat } from "./newChat";
import { PermissionSelect } from "./PermissionSelect";

const DEPS = { createThread: api.createThread };

/**
 * 新会话落地页（设计 2026-10-22 3.11，没选中会话时的 /chat）：直接写第一句话，选好权限与模型，
 * 发送时才建会话；下面是最近的 3 个会话。会话列表的"新建"仍然立刻建一个空会话。
 */
export function NewChatLanding() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const threads = useQuery(threadsQuery);
  const admin = useQuery(modelsAdminQuery);
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const [permission, setPermission] = useState<PermissionMode>("ask");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recentId = useId();
  const model = picked ?? admin.data?.default_chat ?? "";

  const submit = async () => {
    if (!text.trim() || pending) return;
    setPending(true);
    setError(null);
    try {
      const thread = await startNewChat({ text, model, permission }, DEPS);
      await rememberNewThread(queryClient, thread);
      navigate(chatPath(thread.id));
    } catch (failure) {
      setError(`新建会话失败：${readableError(failure)}`);
      setPending(false);
    }
  };

  const recent = [...(threads.data ?? [])]
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .slice(0, 3);
  const now = new Date();

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-6 py-10">
      <div className="m-auto w-full max-w-[45rem]">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <Sparkles aria-hidden="true" className="size-8 text-warning" />
          <h1 className="text-2xl font-semibold">今天想做点什么？</h1>
          <p className="text-sm text-muted-foreground">
            直接写下要做的事，发送时才建会话；Enter 发送，Shift+Enter 换行
          </p>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <div className="rounded-xl border border-border bg-card p-2 shadow-lg focus-within:border-ring">
            <div className="flex items-end gap-2">
              <textarea
                autoFocus
                aria-label="新会话的第一条消息"
                placeholder="想做点什么？"
                rows={3}
                value={text}
                onChange={(event) => setText(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !event.shiftKey &&
                    !isImeComposing(event.nativeEvent)
                  ) {
                    event.preventDefault();
                    void submit();
                  }
                }}
                // 聚焦提示画在外框上（focus-within），输入框自己不画
                className="max-h-48 min-h-20 flex-1 resize-none bg-transparent px-2 py-2 outline-none placeholder:text-muted-foreground"
              />
              <button
                type="submit"
                aria-label="发送"
                disabled={!text.trim() || pending}
                className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity disabled:opacity-30"
              >
                <ArrowUp aria-hidden="true" className="size-4" />
              </button>
            </div>
          </div>
          <div className="mt-2 flex items-center justify-between gap-3 px-1">
            <PermissionSelect value={permission} onChange={setPermission} pendingHint={false} />
            <ModelSelect value={model} onChange={setPicked} />
          </div>
        </form>
        {error && (
          <p role="alert" className="mt-3 text-sm text-danger">
            {error}
          </p>
        )}
        {recent.length > 0 && (
          <section aria-labelledby={recentId} className="mt-10">
            <h2 id={recentId} className="mb-2 px-1 text-[13px] font-medium text-muted-foreground">
              最近的会话
            </h2>
            <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
              {recent.map((thread) => {
                const activity = threadActivity(thread);
                return (
                  <li key={thread.id}>
                    <button
                      type="button"
                      onClick={() => navigate(chatPath(thread.id))}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm transition-colors hover:bg-muted focus-visible:-outline-offset-2"
                    >
                      {activity ? (
                        <StatusDot tone={activity.tone} pulse={activity.pulse} />
                      ) : (
                        <span aria-hidden="true" className="size-2 shrink-0" />
                      )}
                      <span className="min-w-0 flex-1 truncate">{thread.title || "新会话"}</span>
                      <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                        {activity?.label ?? relativeTime(thread.updated_at, now)}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
