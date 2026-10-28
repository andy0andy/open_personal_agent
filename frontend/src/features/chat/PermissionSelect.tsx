import { Check, ChevronDown, ShieldAlert, ShieldCheck, ShieldOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { PermissionMode } from "../../api/types";
import { useEscape } from "../../components/ui/escape";
import { PENDING_HINT, PERMISSIONS, permissionOption, type PermissionOption } from "./permission";

const TONE_CHIP: Record<PermissionOption["tone"], string> = {
  default: "border-border text-muted-foreground hover:text-foreground",
  warning: "border-warning/50 bg-warning/10 text-warning",
  danger: "border-danger/50 bg-danger/10 text-danger",
};
const TONE_TEXT: Record<PermissionOption["tone"], string> = {
  default: "text-foreground",
  warning: "text-warning",
  danger: "text-danger",
};
const ICONS = { ask: ShieldCheck, ask_execute: ShieldAlert, skip: ShieldOff } as const;

/**
 * 会话的审批权限（D23，样式参考 Claude Code 的模式选择）：小标签按钮显示当前档位，
 * 点开向上弹出三档，当前项打勾；风险越大颜色越醒目。
 */
export function PermissionSelect({
  value,
  onChange,
  pendingHint,
}: {
  value: PermissionMode;
  onChange: (value: PermissionMode) => void;
  pendingHint: boolean;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEscape(open, () => setOpen(false));
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const current = permissionOption(value);
  const Icon = ICONS[current.value];
  return (
    <div ref={root} className="relative flex min-w-0 items-center gap-2">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        title="这个会话的审批权限"
        onClick={() => setOpen((shown) => !shown)}
        className={`flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors ${TONE_CHIP[current.tone]}`}
      >
        <Icon className="size-3.5" />
        {current.title}
        <ChevronDown className="size-3" />
      </button>
      {pendingHint && (
        <span className="truncate text-xs text-muted-foreground">{PENDING_HINT}</span>
      )}
      {open && (
        <PermissionMenu
          value={value}
          onChoose={(next) => {
            setOpen(false);
            if (next !== value) onChange(next);
          }}
        />
      )}
    </div>
  );
}

/** 弹出的三档列表（单独导出：静态渲染即可测试）。 */
export function PermissionMenu({
  value,
  onChoose,
}: {
  value: PermissionMode;
  onChoose: (value: PermissionMode) => void;
}) {
  return (
    <div
      role="menu"
      aria-label="会话的审批权限"
      className="absolute bottom-full left-0 z-20 mb-2 w-72 rounded-xl border border-border bg-card p-1 shadow-lg"
    >
      {PERMISSIONS.map((option) => {
        const Icon = ICONS[option.value];
        const checked = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="menuitemradio"
            aria-checked={checked}
            onClick={() => onChoose(option.value)}
            className="flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left hover:bg-muted"
          >
            <Icon className={`mt-0.5 size-4 shrink-0 ${TONE_TEXT[option.tone]}`} />
            <span className="min-w-0 flex-1">
              <span className={`block text-sm ${TONE_TEXT[option.tone]}`}>{option.title}</span>
              <span className="block text-xs text-muted-foreground">{option.description}</span>
            </span>
            {checked && <Check className="mt-0.5 size-4 shrink-0 text-foreground" />}
          </button>
        );
      })}
    </div>
  );
}
