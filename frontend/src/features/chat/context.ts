import type { ContextUsageData } from "../../api/types";
import type { ChatState } from "./reducer";

/**
 * 最近一次主智能体调用的输入 token：它就是下一次调用前上下文的大小（设计 2026-10-22 3.10）。
 * 子智能体、上下文压缩各有各的上下文，不算。
 */
export function lastMainInputTokens(state: ChatState): number | null {
  for (let index = state.items.length - 1; index >= 0; index -= 1) {
    const item = state.items[index];
    if (item?.kind === "usage" && item.usage.caller === "main") return item.usage.input_tokens;
  }
  return null;
}

/** 工具条上的"上下文 N%"：N = 最近一次输入 ÷ 模型最大输入；算不出来时不显示。 */
export function contextLabel(
  inputTokens: number | null,
  maxInputTokens: number | null,
): string | null {
  if (inputTokens === null || !maxInputTokens) return null;
  const percent = (inputTokens / maxInputTokens) * 100;
  return percent > 0 && percent < 1 ? "上下文 <1%" : `上下文 ${Math.round(percent)}%`;
}

/** 工具条上的上下文：占比文字，加上分段（有 context.usage 事件时）。 */
export interface ContextView {
  label: string;
  usage: ContextUsageData | null;
}

/**
 * 有 context.usage 事件时按它的合计与上限算（设计 2026-10-23 4.7），否则退回最近一次主智能体
 * 调用的输入（旧历史）；算不出来时为空。
 */
export function contextView(state: ChatState, maxInputTokens: number | null): ContextView | null {
  const usage = state.context ?? null;
  const label = usage
    ? contextLabel(usage.total, usage.max_input_tokens ?? maxInputTokens)
    : contextLabel(lastMainInputTokens(state), maxInputTokens);
  return label ? { label, usage } : null;
}
