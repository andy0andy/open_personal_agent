import { useQuery } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import { useState, type ReactNode } from "react";
import { readableError } from "../../api/client";
import { PageHeader } from "../../components/ui/PageHeader";
import { Panel } from "../../components/ui/Panel";
import { useCopy } from "../../components/useCopy";
import { usageSummaryQuery } from "../../api/queries";
import type { DayUsage, UsageBucket } from "../../api/types";
import { CountTable } from "./CountTable";
import { formatTokens } from "./format";
import { callerLabel, chartScale, fillDays, toolUsageLabel } from "./summary";

const RANGES = [7, 30, 90] as const;

/**
 * 用量统计页（设计文档 7.7、13.3）：按天看趋势，按模型版本、调用方、会话拆分。
 * onOpenThread：点会话时打开它。
 */
export function UsagePage({ onOpenThread }: { onOpenThread: (threadId: string) => void }) {
  const [days, setDays] = useState<(typeof RANGES)[number]>(30);
  const summary = useQuery(usageSummaryQuery(days));
  const data = summary.data;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title="用量"
        subtitle="按天看趋势，按模型版本、调用方、会话拆分"
        actions={
          <div
            role="radiogroup"
            aria-label="时间范围"
            className="flex rounded-lg border border-border bg-card p-0.5"
          >
            {RANGES.map((value) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={days === value}
                onClick={() => setDays(value)}
                className={`rounded-md px-3 py-1 text-[13px] transition-colors ${
                  days === value
                    ? "bg-accent font-medium text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {`最近 ${value} 天`}
              </button>
            ))}
          </div>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[55rem] space-y-5 p-6">
          {summary.isPending && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <LoaderCircle className="size-4 animate-spin" />
              加载中…
            </p>
          )}
          {summary.isError && (
            <p className="text-sm text-danger">加载失败：{readableError(summary.error)}</p>
          )}
          {data && data.total.calls === 0 && (
            <p className="text-sm text-muted-foreground">这段时间没有调用模型</p>
          )}
          {data && data.total.calls > 0 && (
            <>
              <Totals total={data.total} />
              <Days days={fillDays(data.by_day, data.since, data.until)} />
              <Table
                title="按模型版本"
                rows={data.by_model.map((row) => ({ key: row.model, label: row.model, row }))}
              />
              <Table
                title="按调用方"
                rows={data.by_caller.map((row) => ({
                  key: row.caller,
                  label: callerLabel(row.caller),
                  row,
                }))}
              />
              <Table
                title="用量最多的会话"
                rows={data.by_thread.map((row) => ({
                  key: row.thread_id,
                  label: (
                    <span className="flex items-baseline gap-2">
                      {row.title === null ? (
                        <span className="text-muted-foreground">已删除的会话</span>
                      ) : (
                        <button
                          className="text-left hover:underline"
                          onClick={() => onOpenThread(row.thread_id)}
                        >
                          {row.title || "新会话"}
                        </button>
                      )}
                      <ThreadId id={row.thread_id} />
                    </span>
                  ),
                  row,
                }))}
              />
              <CountTable
                title="工具"
                rows={data.by_tool.map((row) => ({
                  key: row.name,
                  label: (
                    <span className="flex items-baseline gap-2">
                      {toolUsageLabel(row.name)}
                      <span className="font-mono text-xs text-muted-foreground">{row.name}</span>
                    </span>
                  ),
                  count: row.count,
                }))}
              />
              <CountTable
                title="技能"
                rows={data.by_skill.map((row) => ({
                  key: row.name,
                  label: row.name,
                  count: row.count,
                }))}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** 会话 ID 的前 8 位，点一下复制完整 ID：到网关后台按会话筛选时用（docs/usage.md 第 6 节）。 */
function ThreadId({ id }: { id: string }) {
  const { state, copy } = useCopy();
  return (
    <span className="shrink-0 text-xs text-muted-foreground">
      <button
        className="font-mono hover:text-foreground"
        title="复制完整的会话 ID"
        onClick={() => copy(id)}
      >
        {id.slice(0, 8)}
      </button>
      {state === "copied" && <span className="ml-1">已复制</span>}
      {state === "failed" && <span className="ml-1 text-danger">复制失败</span>}
    </span>
  );
}

function Totals({ total }: { total: UsageBucket }) {
  const cards: [string, string, string?][] = [
    ["调用次数", String(total.calls)],
    // 输入 = 实际发给模型的全部输入（含命中缓存的部分），设计 2026-10-19 4.11
    ["输入 token", formatTokens(total.input_tokens), "实际发给模型的全部输入，含命中缓存的部分"],
    ["输出 token", formatTokens(total.output_tokens)],
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {cards.map(([label, value, note]) => (
        <div key={label} className="rounded-xl border border-border bg-card px-4 py-3">
          <p className="text-[13px] text-muted-foreground">{label}</p>
          <p className="mt-1 font-mono text-[22px] leading-tight">{value}</p>
          {note && <p className="mt-1 text-xs text-muted-foreground">{note}</p>}
        </div>
      ))}
    </div>
  );
}

// 柱子的两种颜色：输入 = 正文色 70%，输出 = 成功色加斜纹（设计 2026-10-22 第 4 节；
// 积压小问题 H3：不只靠颜色区分）
const INPUT_BAR = "bg-foreground/70";
const OUTPUT_BAR = "bg-success bar-hatched";

function Legend() {
  return (
    <span className="flex items-center gap-3">
      <span className="flex items-center gap-1">
        <span aria-hidden="true" className={`size-2 rounded-sm ${INPUT_BAR}`} />
        输入
      </span>
      <span className="flex items-center gap-1">
        <span aria-hidden="true" className={`size-2 rounded-sm ${OUTPUT_BAR}`} />
        输出
      </span>
    </span>
  );
}

const barHeight = (value: number, max: number) => ({
  height: `${(value / max) * 100}%`,
  // 用得很少的日子也看得见一点
  minHeight: value > 0 ? 2 : 0,
});

/**
 * 每日柱状图（设计 2026-10-22 第 4 节）：每天一根，输入与输出叠放；左侧刻度、虚线网格、
 * 底部首中尾日期；悬停或用键盘聚焦一根柱子时显示浮层（日期、调用、输入、输出）。
 */
function Days({ days }: { days: DayUsage[] }) {
  const [active, setActive] = useState<number | null>(null);
  const { max, ticks } = chartScale(days.map((day) => day.input_tokens + day.output_tokens));
  const shown = active === null ? undefined : days[active];
  const middle = days[Math.floor((days.length - 1) / 2)];
  return (
    <Panel title="每天的用量" note={<Legend />}>
      <div className="flex gap-2">
        <div
          aria-hidden="true"
          className="flex h-44 w-11 shrink-0 flex-col justify-between text-right font-mono text-[11px] leading-none text-muted-foreground"
        >
          {ticks.map((tick) => (
            <span key={tick}>{formatTokens(tick)}</span>
          ))}
        </div>
        <div className="relative h-44 min-w-0 flex-1">
          {ticks.map((tick) => (
            <div
              key={tick}
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 border-t border-dashed border-border"
              style={{ top: `${(1 - tick / max) * 100}%` }}
            />
          ))}
          <div className="absolute inset-0 flex items-end gap-px">
            {days.map((day, index) => (
              <button
                key={day.day}
                type="button"
                aria-label={`${day.day}：${day.calls} 次调用，输入 ${formatTokens(day.input_tokens)}，输出 ${formatTokens(day.output_tokens)}`}
                onMouseEnter={() => setActive(index)}
                onMouseLeave={() => setActive(null)}
                onFocus={() => setActive(index)}
                onBlur={() => setActive(null)}
                className={`flex h-full min-w-0 flex-1 flex-col justify-end gap-px rounded-t-sm transition-colors ${
                  active === index ? "bg-muted" : ""
                }`}
              >
                <span
                  className={`w-full rounded-t-sm ${OUTPUT_BAR}`}
                  style={barHeight(day.output_tokens, max)}
                />
                <span className={`w-full ${INPUT_BAR}`} style={barHeight(day.input_tokens, max)} />
              </button>
            ))}
          </div>
          {shown && active !== null && (
            <DayTooltip day={shown} position={(active + 0.5) / days.length} />
          )}
        </div>
      </div>
      <div
        aria-hidden="true"
        className="mt-1.5 ml-13 flex justify-between font-mono text-[11px] text-muted-foreground"
      >
        <span>{days[0]?.day}</span>
        {days.length > 2 && <span>{middle?.day}</span>}
        <span>{days.at(-1)?.day}</span>
      </div>
    </Panel>
  );
}

/** 浮层画在图表区里面靠上（往上画会被卡片的圆角裁掉日期那一行）；靠近两边时不出图表。 */
function DayTooltip({ day, position }: { day: DayUsage; position: number }) {
  const align =
    position < 0.15 ? "translate-x-0" : position > 0.85 ? "-translate-x-full" : "-translate-x-1/2";
  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none absolute top-1 z-10 ${align} rounded-lg border border-border bg-card px-3 py-2 text-xs whitespace-nowrap shadow-lg`}
      style={{ left: `${position * 100}%` }}
    >
      <p className="mb-1 font-mono font-medium">{day.day}</p>
      <p className="text-muted-foreground">{`${day.calls} 次调用`}</p>
      <p className="flex items-center gap-1.5">
        <span aria-hidden="true" className={`size-2 rounded-sm ${INPUT_BAR}`} />
        {`输入 ${formatTokens(day.input_tokens)}`}
      </p>
      <p className="flex items-center gap-1.5">
        <span aria-hidden="true" className={`size-2 rounded-sm ${OUTPUT_BAR}`} />
        {`输出 ${formatTokens(day.output_tokens)}`}
      </p>
    </div>
  );
}

function Table({
  title,
  rows,
}: {
  title: string;
  rows: { key: string; label: ReactNode; row: UsageBucket }[];
}) {
  if (rows.length === 0) return null;
  return (
    <Panel title={title}>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm [&_td]:py-2 [&_td]:pr-4 [&_th]:pr-4 [&_th]:pb-2 [&_th]:font-normal">
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th>名称</th>
              <th className="text-right">调用</th>
              <th className="text-right">输入</th>
              <th className="text-right">输出</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ key, label, row }) => (
              <tr key={key} className="border-t border-border">
                <td>{label}</td>
                <td className="text-right font-mono tabular-nums">{row.calls}</td>
                <td className="text-right font-mono tabular-nums">
                  {formatTokens(row.input_tokens)}
                </td>
                <td className="text-right font-mono tabular-nums">
                  {formatTokens(row.output_tokens)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
