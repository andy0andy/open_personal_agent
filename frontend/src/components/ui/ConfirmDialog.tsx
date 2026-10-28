import { useRef, type ReactNode } from "react";
import { Button } from "./Button";
import { useDialog } from "./dialogFocus";

/** 破坏性操作前的确认框（设计文档反目标：删除等操作必须先确认）。打开时焦点在"取消"上。 */
export function ConfirmDialog({
  title,
  open,
  confirmLabel,
  danger = false,
  onConfirm,
  onCancel,
  children,
}: {
  title: string;
  open: boolean;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children: ReactNode;
}) {
  const cancel = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLDivElement>(null);
  useDialog(open, onCancel, box, () => cancel.current);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/70"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div
        ref={box}
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="w-full max-w-sm rounded-xl border border-border bg-card p-5 shadow-lg"
      >
        <h2 className="font-medium">{title}</h2>
        <div className="mt-3 space-y-2 text-sm text-muted-foreground">{children}</div>
        <div className="mt-5 flex justify-end gap-2">
          <Button ref={cancel} onClick={onCancel}>
            取消
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
