import { useAuiState } from "@assistant-ui/react";
import { ChevronDown, Copy, RotateCcw, StepForward, TriangleAlert } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { errorButtons, errorKindOf, switchableModels } from "../../features/chat/retry";
import { Button } from "../ui/Button";
import { closesOverlay } from "../ui/escape";
import { moveMenuFocus } from "../ui/menuKeys";
import { useCopy } from "../useCopy";
import type { ErrorInfo } from "./adapter";
import { RetryActionsContext } from "./retryActions";

/** "换个模型"：列出可换的对话模型，选一个就改会话的模型，再重试这一轮或继续。 */
function SwitchModel({ models, onPick }: { models: string[]; onPick: (model: string) => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    // 打开时把焦点移进菜单，上下方向键才能选（同会话菜单）
    box.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    const closeOutside = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", closeOutside);
    return () => document.removeEventListener("mousedown", closeOutside);
  }, [open]);
  return (
    <div
      ref={box}
      className="relative"
      onKeyDown={(event) => {
        if (closesOverlay(event.nativeEvent) && open) {
          setOpen(false);
          trigger.current?.focus();
        } else if (open) {
          moveMenuFocus(event);
        }
      }}
    >
      <Button
        ref={trigger}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        换个模型
        <ChevronDown aria-hidden="true" className="size-3.5" />
      </Button>
      {open && (
        <div
          role="menu"
          aria-label="选择模型"
          className="absolute bottom-full left-0 z-20 mb-1 max-h-64 min-w-56 overflow-y-auto rounded-lg border border-border bg-card p-1 shadow-lg"
        >
          {models.map((model) => (
            <button
              key={model}
              type="button"
              role="menuitem"
              className="block w-full truncate rounded-md px-2.5 py-1.5 text-left font-mono text-[13px] hover:bg-muted"
              onClick={() => {
                setOpen(false);
                onPick(model);
              }}
            >
              {model}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * 运行失败的报错卡片（设计 2026-10-22 3.8、2026-10-23 4.5）：标题是报错原文；最后一轮出错时按类型给按钮——
 * 额度用完、上下文超长只能换个模型；其余没有副作用时"重试这一轮"，做过有副作用的操作时"继续"（D26）。
 * 总能"复制详情"。
 */
export function ErrorCard() {
  const error = useAuiState(({ message }) =>
    message.status?.type === "incomplete" && message.status.reason === "error"
      ? String(message.status.error ?? "运行失败")
      : null,
  );
  const info = useAuiState(({ message }) => message.metadata.custom.error) as ErrorInfo | undefined;
  const isLast = useAuiState(({ message }) => message.isLast);
  const actions = useContext(RetryActionsContext);
  const { state: copyState, copy } = useCopy();
  if (error === null) return null;
  const kind = info?.kind ?? errorKindOf(null, error);
  const retryable = info?.retryable ?? false;
  const buttons = isLast && info ? errorButtons(kind, retryable) : ["copy"];
  const models = switchableModels(actions.models, kind, actions.current);
  return (
    <div className="mt-2 rounded-xl border border-danger bg-danger-soft p-3.5 text-sm">
      <p className="flex items-start gap-2 text-foreground">
        <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-danger" />
        <span className="min-w-0 break-words whitespace-pre-wrap">{error}</span>
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {buttons.includes("retry") && info && (
          <Button onClick={() => actions.retry(info.runId)}>
            <RotateCcw aria-hidden="true" className="size-3.5" />
            重试这一轮
          </Button>
        )}
        {buttons.includes("continue") && (
          <Button
            onClick={actions.continueTurn}
            title="这一轮已经做过会改动东西的操作，重跑会再做一遍"
          >
            <StepForward aria-hidden="true" className="size-3.5" />
            继续
          </Button>
        )}
        {buttons.includes("switch") && info && models.length > 0 && (
          <SwitchModel
            models={models}
            onPick={(model) => actions.switchModel(model, info.runId, retryable)}
          />
        )}
        <Button variant="ghost" onClick={() => copy(error)}>
          <Copy aria-hidden="true" className="size-3.5" />
          {copyState === "copied" ? "已复制" : copyState === "failed" ? "复制失败" : "复制详情"}
        </Button>
      </div>
    </div>
  );
}
