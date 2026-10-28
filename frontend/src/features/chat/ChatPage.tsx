import { useQuery } from "@tanstack/react-query";
import { PanelLeftOpen } from "lucide-react";
import { useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router";
import { threadQuery, threadsQuery } from "../../api/queries";
import { PATHS, chatPath, pageTitle } from "../../layout/routes";
import { ThreadList } from "../threads/ThreadList";
import { ChatView } from "./ChatView";
import { NewChatLanding } from "./NewChatLanding";

const COLLAPSED_KEY = "opa.threadColumn.collapsed";

/** 浏览器不让用本地存储时（隐私模式等）按展开处理。 */
function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function writeCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0");
  } catch {
    // 记不住也不影响使用
  }
}

/**
 * 对话页（设计文档 4）：第二栏是会话列表（可收起），右边是对话区。地址带会话 ID；
 * 没选会话时是新会话落地页（设计 2026-10-22 3.11）；ID 无效或会话已删时回到 /chat。
 */
export function ChatPage() {
  const { threadId } = useParams();
  const navigate = useNavigate();
  const threads = useQuery(threadsQuery);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  // 每次都从会话列表里取最新的会话对象，标题等信息随列表刷新而更新
  const listed = threads.data?.find((item) => item.id === threadId) ?? null;
  // 列表里没有的（如已归档的、搜索结果点进来的）按 ID 取（设计 2026-10-23 6.1）
  const single = useQuery({
    ...threadQuery(threadId ?? ""),
    enabled: Boolean(threadId) && threads.isSuccess && listed === null,
  });
  const thread = listed ?? single.data ?? null;
  const looking = Boolean(threadId) && thread === null && !single.isError;

  if (threadId && threads.isSuccess && listed === null && single.isError) {
    return <Navigate to={PATHS.chat} replace />;
  }

  const toggle = (next: boolean) => {
    setCollapsed(next);
    writeCollapsed(next);
  };

  return (
    <div className="flex min-h-0 flex-1">
      <title>{pageTitle(chatPath(threadId), thread?.title)}</title>
      {collapsed ? (
        <div className="flex w-10 shrink-0 flex-col items-center border-r border-border py-3">
          <button
            aria-label="展开会话列表"
            title="展开会话列表"
            className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={() => toggle(false)}
          >
            <PanelLeftOpen className="size-4" />
          </button>
        </div>
      ) : (
        <div className="flex w-70 shrink-0 flex-col border-r border-border bg-card/40 p-3">
          <ThreadList
            selectedId={thread?.id ?? null}
            onSelect={(id) => navigate(chatPath(id))}
            onCollapse={() => toggle(true)}
          />
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        {thread ? (
          <ChatView thread={thread} />
        ) : looking ? (
          <p className="p-6 text-sm text-muted-foreground">加载中…</p>
        ) : (
          <NewChatLanding />
        )}
      </div>
    </div>
  );
}
