import {
  BarChart3,
  BookMarked,
  Cpu,
  MessageSquare,
  Plug,
  Settings,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

/** 每页一个地址（设计文档 2026-10-18 管理页面 3.2）：刷新、收藏都能回到原页。 */
export const PATHS = {
  chat: "/chat",
  knowledge: "/knowledge",
  usage: "/usage",
  models: "/models",
  skills: "/skills",
  mcp: "/mcp",
  settings: "/settings",
} as const;

/** 对话页地址：带会话 ID 时刷新后回到同一会话。 */
export function chatPath(threadId?: string | null): string {
  return threadId ? `${PATHS.chat}/${threadId}` : PATHS.chat;
}

export interface NavItem {
  label: string;
  path: string;
  icon: LucideIcon;
}

/** 侧栏的两组入口，组与组之间留间隔（设计文档 3.1）。 */
export const NAV_GROUPS: { title: "工作" | "管理"; items: NavItem[] }[] = [
  {
    title: "工作",
    items: [
      { label: "对话", path: PATHS.chat, icon: MessageSquare },
      { label: "知识库", path: PATHS.knowledge, icon: BookMarked },
      { label: "用量", path: PATHS.usage, icon: BarChart3 },
    ],
  },
  {
    title: "管理",
    items: [
      { label: "模型", path: PATHS.models, icon: Cpu },
      { label: "技能", path: PATHS.skills, icon: Sparkles },
      { label: "MCP", path: PATHS.mcp, icon: Plug },
      { label: "设置", path: PATHS.settings, icon: Settings },
    ],
  },
];

const APP_NAME = "个人智能体";

/**
 * 浏览器标签页的标题（积压小问题 F16）：每页写页名，对话页写会话标题（没有标题写"新会话"；
 * 会话还没取到时写"对话"），后面都带应用名。
 */
export function pageTitle(pathname: string, threadTitle?: string | null): string {
  if (pathname.startsWith(`${PATHS.chat}/`) && threadTitle !== undefined && threadTitle !== null) {
    return `${threadTitle || "新会话"} · ${APP_NAME}`;
  }
  const item = NAV_GROUPS.flatMap((group) => group.items).find(
    (nav) => pathname === nav.path || pathname.startsWith(`${nav.path}/`),
  );
  return item ? `${item.label} · ${APP_NAME}` : APP_NAME;
}
