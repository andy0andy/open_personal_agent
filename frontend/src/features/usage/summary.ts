import type { DayUsage } from "../../api/types";
import { toolLabel } from "../../components/chat/tools";

const CALLERS: Record<string, string> = {
  main: "主智能体",
  compaction: "上下文压缩",
  title: "生成标题",
  memory_extraction: "整理记忆",
  embedding: "向量化",
};

/** 调用方的中文名；不认识的是子智能体（以它的名字作调用方）。 */
export function callerLabel(caller: string): string {
  return CALLERS[caller] ?? `子智能体 ${caller}`;
}

/** 从 since 到 until（含）每天一项：没有调用的日子补 0。日期是 YYYY-MM-DD。 */
export function fillDays(byDay: DayUsage[], since: string, until: string): DayUsage[] {
  const known = new Map(byDay.map((day) => [day.day, day]));
  const days: DayUsage[] = [];
  // 按 UTC 逐日推进：只做日期运算，不受浏览器时区与夏令时影响
  for (let at = new Date(`${since}T00:00:00Z`); ; at.setUTCDate(at.getUTCDate() + 1)) {
    const key = at.toISOString().slice(0, 10);
    if (key > until) break;
    days.push(
      known.get(key) ?? {
        day: key,
        calls: 0,
        input_tokens: 0,
        output_tokens: 0,
      },
    );
  }
  return days;
}

/**
 * 每日柱状图的纵轴（设计 2026-10-22 第 4 节）：顶端取 1.5、3、6 × 10ⁿ 里不小于最大值的最小者，
 * 三等分后的刻度都是整数（如 600k、400k、200k、0）；全为 0 时顶端为 3。
 */
export function chartScale(values: number[]): { max: number; ticks: number[] } {
  const peak = Math.max(0, ...values);
  let max = 3;
  if (peak > 3) {
    let unit = 10 ** Math.floor(Math.log10(peak));
    // 从这一数量级的 1.5 倍开始往上找
    for (;;) {
      const fit = [1.5, 3, 6].map((step) => step * unit).find((candidate) => candidate >= peak);
      if (fit !== undefined) {
        max = fit;
        break;
      }
      unit *= 10;
    }
  }
  return { max, ticks: [max, (max * 2) / 3, max / 3, 0] };
}

/** 工具用量里的工具名（设计 2026-10-23 6.8）：同对话里工具行的说法；MCP 工具写"外部工具 · 服务 · 工具"。 */
export function toolUsageLabel(name: string): string {
  const { verb, detail, kind } = toolLabel(name, {});
  return kind === "external" ? `${verb} · ${detail}` : verb;
}
