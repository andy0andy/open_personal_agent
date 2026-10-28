import { TriangleAlert } from "lucide-react";
import { useRef } from "react";
import { readableError } from "../../api/client";
import { useDialog } from "../../components/ui/dialogFocus";

/** 删除会话前的确认弹窗：Esc 或"取消"关闭；删除失败（如会话正在运行）时在弹窗里显示原因。 */
export function DeleteThreadDialog({
  title,
  pending,
  error,
  onConfirm,
  onCancel,
  returnFocus,
}: {
  title: string;
  pending: boolean;
  error: unknown;
  onConfirm: () => void;
  onCancel: () => void;
  /** 关闭后焦点回到它：从菜单打开时，打开前的焦点（菜单项）已随菜单移除 */
  returnFocus?: HTMLElement | null;
}) {
  const box = useRef<HTMLDivElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  // 一直挂着才显示：打开即生效；焦点先在"取消"上（与确认框一致）
  useDialog(
    true,
    onCancel,
    box,
    () => cancel.current,
    () => returnFocus,
  );

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
        tabIndex={-1}
        aria-labelledby="delete-thread-title"
        className="w-full max-w-sm rounded-xl border border-border bg-card p-5 shadow-lg"
      >
        <h2 id="delete-thread-title" className="flex items-center gap-2 font-medium">
          <TriangleAlert className="size-4 text-danger" />
          删除会话
        </h2>
        <p className="mt-3 text-sm text-muted-foreground">
          确定删除会话「<span className="text-foreground">{title}</span>
          」？对话内容将全部删除，无法恢复。它记下的记忆、加入知识库的文档会保留，可在知识库页管理。
        </p>
        {error !== null && error !== undefined && (
          <p className="mt-3 text-sm text-danger">删除失败：{readableError(error)}</p>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button
            ref={cancel}
            className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-muted"
            disabled={pending}
            onClick={onCancel}
          >
            取消
          </button>
          <button
            className="rounded-lg bg-danger px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-50"
            disabled={pending}
            onClick={onConfirm}
          >
            {pending ? "正在删除…" : "删除"}
          </button>
        </div>
      </div>
    </div>
  );
}
