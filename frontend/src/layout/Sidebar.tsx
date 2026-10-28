import { Bot } from "lucide-react";
import { useState } from "react";
import { NavLink, useLocation } from "react-router";
import { AppearanceToggle } from "../features/settings/AppearanceToggle";
import { NAV_GROUPS, PATHS } from "./routes";

/**
 * 左侧栏（设计 2026-10-22 2.3）：品牌字、工作 / 管理两组入口（显示组名）、底部明暗切换。
 * 窗口窄于 1280px 时只显示图标，名字放在 aria-label 与悬停提示里，给对话区多留宽度。
 * 会话列表在对话页的第二栏，不在这里。
 * "对话"指向最后打开的会话：去别的页看一眼再回来，还在原来的会话里（会话已删时对话页自己退回空状态）。
 */
export function Sidebar() {
  const { pathname } = useLocation();
  const [chatTarget, setChatTarget] = useState<string>(PATHS.chat);
  const onChat = pathname === PATHS.chat || pathname.startsWith(`${PATHS.chat}/`);
  if (onChat && chatTarget !== pathname) setChatTarget(pathname);

  return (
    <aside className="flex w-14 shrink-0 flex-col gap-5 border-r border-border bg-card/60 px-2 py-3 xl:w-52 xl:px-3">
      <div className="flex h-8 items-center justify-center gap-2 xl:justify-start xl:px-2">
        <Bot className="size-5 shrink-0 text-warning" aria-hidden="true" />
        <span className="hidden font-mono text-sm tracking-widest uppercase xl:inline">
          Personal Agent
        </span>
      </div>
      {NAV_GROUPS.map((group) => (
        <div
          key={group.title}
          role="group"
          aria-label={group.title}
          className="flex flex-col gap-0.5"
        >
          <div
            aria-hidden="true"
            className="hidden px-2 pb-1 text-xs text-muted-foreground xl:block"
          >
            {group.title}
          </div>
          {group.items.map(({ label, path, icon: Icon }) => (
            <NavLink
              key={path}
              to={path === PATHS.chat ? chatTarget : path}
              aria-label={label}
              title={label}
              className={({ isActive }) =>
                `flex h-9 items-center justify-center gap-2.5 rounded-lg px-2 text-sm transition-colors xl:justify-start ${
                  isActive
                    ? "bg-accent font-medium text-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`
              }
            >
              <Icon className="size-4 shrink-0" aria-hidden="true" />
              <span className="hidden xl:inline">{label}</span>
            </NavLink>
          ))}
        </div>
      ))}
      <div className="mt-auto">
        <AppearanceToggle />
      </div>
    </aside>
  );
}
