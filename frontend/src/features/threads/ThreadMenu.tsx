import { Archive, ArchiveRestore, Download, Pencil, Trash2 } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { moveMenuFocus } from "../../components/ui/menuKeys";
import { clampToViewport } from "./menu";

export interface MenuPosition {
  threadId: string;
  x: number;
  y: number;
  /** 打开菜单的元素（"⋯"按钮或会话行）：按 Esc 关闭后焦点回到它。 */
  trigger: HTMLElement | null;
}

/**
 * 会话的操作菜单（悬停"⋯"或右键打开）：点菜单外、按 Esc、滚动时关闭。
 * 打开后焦点在第一项，上下方向键切换；靠近窗口边缘时收回窗口内。
 */
export function ThreadMenu({
  position,
  onRename,
  onDelete,
  onClose,
  onExport,
  onArchive,
  archived = false,
}: {
  position: MenuPosition;
  onRename: (threadId: string) => void;
  onDelete: (threadId: string) => void;
  onClose: () => void;
  /** 只有顶栏的菜单给：导出 Markdown（设计 2026-10-23 6.2）。 */
  onExport?: (threadId: string) => void;
  /** 归档或取消归档（设计 2026-10-23 6.5）：传入要改成的状态。 */
  onArchive?: (threadId: string, archived: boolean) => void;
  archived?: boolean;
}) {
  const menu = useRef<HTMLDivElement>(null);
  const [placed, setPlaced] = useState({ x: position.x, y: position.y });

  useLayoutEffect(() => {
    const rect = menu.current?.getBoundingClientRect();
    const size = { width: rect?.width ?? 0, height: rect?.height ?? 0 };
    const viewport = { width: window.innerWidth, height: window.innerHeight };
    setPlaced(clampToViewport(position, size, viewport));
    menu.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
  }, [position]);

  useEffect(() => {
    const closeOutside = (event: MouseEvent) => {
      if (!menu.current?.contains(event.target as Node)) onClose();
    };
    document.addEventListener("mousedown", closeOutside);
    window.addEventListener("scroll", onClose, true);
    window.addEventListener("resize", onClose);
    return () => {
      document.removeEventListener("mousedown", closeOutside);
      window.removeEventListener("scroll", onClose, true);
      window.removeEventListener("resize", onClose);
    };
  }, [onClose]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      onClose();
      position.trigger?.focus();
      return;
    }
    moveMenuFocus(event);
  };

  return (
    <div
      ref={menu}
      role="menu"
      aria-label="会话操作"
      className="fixed z-50 min-w-32 rounded-lg border border-border bg-card p-1 text-sm shadow-lg"
      style={{ left: placed.x, top: placed.y }}
      onKeyDown={onKeyDown}
      onBlur={(event) => {
        // 用 Tab 把焦点移出菜单时关闭；移到"⋯"按钮上不算（那是在点它收起菜单，由按钮处理）
        const next = event.relatedTarget as Node | null;
        if (next !== position.trigger && !event.currentTarget.contains(next)) onClose();
      }}
    >
      <button
        role="menuitem"
        tabIndex={-1}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left outline-none hover:bg-muted focus-visible:bg-muted"
        onClick={() => onRename(position.threadId)}
      >
        <Pencil className="size-3.5" />
        重命名
      </button>
      {onArchive && (
        <button
          role="menuitem"
          tabIndex={-1}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left outline-none hover:bg-muted focus-visible:bg-muted"
          onClick={() => onArchive(position.threadId, !archived)}
        >
          {archived ? <ArchiveRestore className="size-3.5" /> : <Archive className="size-3.5" />}
          {archived ? "取消归档" : "归档"}
        </button>
      )}
      {onExport && (
        <button
          role="menuitem"
          tabIndex={-1}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left outline-none hover:bg-muted focus-visible:bg-muted"
          onClick={() => onExport(position.threadId)}
        >
          <Download className="size-3.5" />
          导出 Markdown
        </button>
      )}
      <button
        role="menuitem"
        tabIndex={-1}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-danger outline-none hover:bg-danger/10 focus-visible:bg-danger/10"
        onClick={() => onDelete(position.threadId)}
      >
        <Trash2 className="size-3.5" />
        删除
      </button>
    </div>
  );
}
