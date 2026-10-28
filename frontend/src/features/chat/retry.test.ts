import { describe, expect, it } from "vitest";
import { errorButtons, errorKindOf, isQuotaError, switchableModels } from "./retry";

describe("额度用完", () => {
  it("以“模型额度用完了”开头的才算", () => {
    expect(isQuotaError("模型额度用完了（模型服务返回余额或配额不足）。")).toBe(true);
    expect(isQuotaError("模型网关不可用")).toBe(false);
  });
});

describe("报错类型（设计 2026-10-23 4.5）", () => {
  it("有类型时照用", () => {
    expect(errorKindOf("rate_limit", "RateLimitError: slow down")).toBe("rate_limit");
  });

  it("旧历史没有类型：认得出额度用完的算 quota，其余算 other", () => {
    expect(errorKindOf(undefined, "模型额度用完了（模型服务返回余额或配额不足）。")).toBe("quota");
    expect(errorKindOf(null, "模型网关不可用")).toBe("other");
  });
});

describe("报错卡片的按钮（设计 2026-10-23 4.5）", () => {
  it("额度用完、上下文超长：只能换个模型", () => {
    expect(errorButtons("quota", true)).toEqual(["switch", "copy"]);
    expect(errorButtons("context_overflow", true)).toEqual(["switch", "copy"]);
  });

  it("其余：没有副作用时重试这一轮，有副作用时只能继续", () => {
    expect(errorButtons("gateway", true)).toEqual(["retry", "switch", "copy"]);
    expect(errorButtons("stalled", false)).toEqual(["continue", "switch", "copy"]);
  });

  const models = [
    { name: "small", maxInputTokens: 200_000 },
    { name: "big", maxInputTokens: 1_000_000 },
    { name: "unknown", maxInputTokens: null },
  ];

  it("换个模型：不列当前的；上下文超长时只列上下文更长的", () => {
    expect(switchableModels(models, "gateway", "small")).toEqual(["big", "unknown"]);
    expect(switchableModels(models, "context_overflow", "small")).toEqual(["big"]);
    expect(switchableModels(models, "context_overflow", "big")).toEqual([]);
  });
});
