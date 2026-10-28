import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router";
import { ChatPage } from "../features/chat/ChatPage";
import { KnowledgePage } from "../features/knowledge/KnowledgePage";
import { McpPage } from "../features/mcp/McpPage";
import { ModelsPage } from "../features/models/ModelsPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { SkillsPage } from "../features/skills/SkillsPage";
import { UsagePage } from "../features/usage/UsagePage";
import { PATHS, chatPath, pageTitle } from "./routes";
import { Sidebar } from "./Sidebar";

/** 整体布局（设计文档 2026-10-18 管理页面 3）：左侧栏 + 每页一个地址的内容区。 */
export function AppShell() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  return (
    <div className="app-glow flex h-screen bg-background text-foreground">
      {/* 对话页自己写标题（要用会话标题）；React 19 会把 <title> 放进 head */}
      {!pathname.startsWith(PATHS.chat) && <title>{pageTitle(pathname)}</title>}
      <Sidebar />
      <main className="flex min-w-0 flex-1 flex-col">
        <Routes>
          <Route path="/" element={<Navigate to={PATHS.chat} replace />} />
          <Route path={`${PATHS.chat}/:threadId?`} element={<ChatPage />} />
          <Route path={PATHS.knowledge} element={<KnowledgePage />} />
          <Route
            path={PATHS.usage}
            element={<UsagePage onOpenThread={(threadId) => navigate(chatPath(threadId))} />}
          />
          <Route path={PATHS.models} element={<ModelsPage />} />
          <Route path={PATHS.skills} element={<SkillsPage />} />
          <Route path={PATHS.mcp} element={<McpPage />} />
          <Route path={PATHS.settings} element={<SettingsPage />} />
          <Route path="*" element={<Navigate to={PATHS.chat} replace />} />
        </Routes>
      </main>
    </div>
  );
}
