import type { ContextUsageData } from "../../api/types";
import { formatTokens } from "../usage/format";

const SEGMENTS: { key: keyof ContextUsageData; name: string; color: string }[] = [
  { key: "system", name: "系统提示词", color: "bg-primary" },
  { key: "profile", name: "常驻记忆", color: "bg-success" },
  { key: "tools", name: "工具定义", color: "bg-info" },
  { key: "related", name: "相关记忆", color: "bg-warning" },
  { key: "history", name: "对话历史", color: "bg-muted-foreground" },
];

const percent = (part: number, whole: number) =>
  whole > 0 ? `${Math.round((part / whole) * 100)}%` : "0%";

/**
 * 工具条上的"上下文 N%"（设计 2026-10-23 4.7）：悬停、获得焦点或点一下时，弹出分段条与五个部分
 * 各自的大小与占比。旧历史没有分段，只显示占比。
 */
export function ContextMeter({ label, usage }: { label: string; usage: ContextUsageData | null }) {
  if (!usage) {
    return (
      <span className="shrink-0 text-xs whitespace-nowrap text-muted-foreground">{label}</span>
    );
  }
  const total = usage.total;
  return (
    <span className="group relative shrink-0">
      <button
        type="button"
        className="rounded-md px-1 text-xs whitespace-nowrap text-muted-foreground hover:text-foreground"
        aria-label={`${label}，查看各部分`}
      >
        {label}
      </button>
      <span
        role="tooltip"
        className="invisible absolute right-0 bottom-full z-20 mb-1 w-64 rounded-lg border border-border bg-card p-3 text-xs text-foreground shadow-lg group-focus-within:visible group-hover:visible"
      >
        <span className="mb-2 flex h-2 w-full overflow-hidden rounded-full bg-muted">
          {SEGMENTS.map(({ key, color }) => (
            <span
              key={key}
              className={color}
              style={{ width: percent(Number(usage[key]), total) }}
            />
          ))}
        </span>
        {SEGMENTS.map(({ key, name, color }) => (
          <span key={key} className="flex items-center justify-between gap-2 py-0.5">
            <span className="flex items-center gap-1.5">
              <span className={`size-2 rounded-full ${color}`} aria-hidden="true" />
              {name}
            </span>
            <span className="font-mono text-muted-foreground">
              {formatTokens(Number(usage[key]))}（{percent(Number(usage[key]), total)}）
            </span>
          </span>
        ))}
        <span className="mt-1 flex justify-between border-t border-border pt-1 font-mono">
          <span>合计</span>
          <span>
            {formatTokens(total)}
            {usage.max_input_tokens ? ` / ${formatTokens(usage.max_input_tokens)}` : ""}
          </span>
        </span>
      </span>
    </span>
  );
}
