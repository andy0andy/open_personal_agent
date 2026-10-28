import type { ErrorKind } from "../../api/types";

/** 额度用完（后端的说法以"模型额度用完了"开头，D23）：旧历史没有报错类型时靠它认出来。 */
export function isQuotaError(text: string): boolean {
  return text.startsWith("模型额度用完了");
}

/** 报错的类型：旧历史没有类型时，认得出额度用完的算 quota，其余算 other（设计 2026-10-23 4.5）。 */
export function errorKindOf(kind: ErrorKind | null | undefined, text: string): ErrorKind {
  if (kind) return kind;
  return isQuotaError(text) ? "quota" : "other";
}

export type ErrorButton = "retry" | "continue" | "switch" | "copy";

/**
 * 报错卡片按类型给的按钮（设计 2026-10-23 4.5）：额度用完、上下文超长时重试没用，只能换个模型；
 * 其余没有副作用时"重试这一轮"，做过有副作用的操作时只能"继续"（D26）。
 */
export function errorButtons(kind: ErrorKind, retryable: boolean): ErrorButton[] {
  if (kind === "quota" || kind === "context_overflow") return ["switch", "copy"];
  return [retryable ? "retry" : "continue", "switch", "copy"];
}

/** 可以换的对话模型与它的上下文上限。 */
export interface ModelChoice {
  name: string;
  maxInputTokens: number | null;
}

/** "换个模型"能选的：不列当前的；上下文超长时只列上下文比当前更长的。 */
export function switchableModels(
  models: readonly ModelChoice[],
  kind: ErrorKind,
  current: string,
): string[] {
  const limit = models.find((model) => model.name === current)?.maxInputTokens ?? 0;
  return models
    .filter(
      (model) =>
        model.name !== current &&
        (kind !== "context_overflow" || (model.maxInputTokens ?? 0) > limit),
    )
    .map((model) => model.name);
}
