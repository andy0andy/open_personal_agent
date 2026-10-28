import { X } from "lucide-react";
import { useRef, type ReactNode } from "react";
import { useDialog } from "./dialogFocus";

/** 右侧抽屉：新增、编辑、查看详情用。按 Esc 或点遮罩关闭；打开时焦点移到里面第一个输入框。 */
export function Drawer({
  title,
  open,
  onClose,
  footer,
  children,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  footer?: ReactNode;
  children: ReactNode;
}) {
  const body = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  // 先聚焦正文里第一个输入框；正文里没有可聚焦的（如没有工具的工具抽屉）就是"关闭"按钮
  useDialog(open, onClose, box, () =>
    body.current?.querySelector<HTMLElement>("input, select, textarea, button"),
  );
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-background/60"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={box}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="flex h-full w-full max-w-md flex-col border-l border-border bg-card"
      >
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <h2 className="truncate font-medium">{title}</h2>
          <button
            aria-label="关闭"
            className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={onClose}
          >
            <X className="size-4" />
          </button>
        </div>
        <div ref={body} className="flex-1 space-y-4 overflow-y-auto p-4">
          {children}
        </div>
        {footer && (
          <div className="flex items-center gap-2 border-t border-border px-4 py-3">{footer}</div>
        )}
      </div>
    </div>
  );
}
