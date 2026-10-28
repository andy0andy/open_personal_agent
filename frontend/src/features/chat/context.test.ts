import { describe, expect, it } from "vitest";
import type { ContextUsageData, UsageData } from "../../api/types";
import { contextLabel, contextView, lastMainInputTokens } from "./context";
import type { ChatItem, ChatState } from "./reducer";

const usage = (id: string, caller: string, input: number): ChatItem => ({
  kind: "usage",
  id,
  usage: { caller, input_tokens: input, output_tokens: 1 } as UsageData,
});
const chat = (...items: ChatItem[]): ChatState => ({ items, running: false });

describe("最近一次主智能体调用的输入", () => {
  it("取最后一条主智能体的用量，跳过子智能体与上下文压缩", () => {
    const state = chat(
      usage("u1", "main", 1000),
      usage("u2", "main", 21500),
      usage("u3", "researcher", 90000),
      usage("u4", "compaction", 80000),
    );
    expect(lastMainInputTokens(state)).toBe(21500);
  });

  it("还没有调用过模型：没有", () => {
    expect(lastMainInputTokens(chat({ kind: "user", id: "m", text: "你好" }))).toBeNull();
  });
});

describe("上下文占比", () => {
  it("按模型最大输入算百分比", () => {
    expect(contextLabel(21500, 1000000)).toBe("上下文 2%");
    expect(contextLabel(300, 1000000)).toBe("上下文 <1%");
  });

  it("算不出来时不显示", () => {
    expect(contextLabel(null, 1000)).toBeNull();
    expect(contextLabel(10, null)).toBeNull();
    expect(contextLabel(10, 0)).toBeNull();
  });
});

describe("上下文分段（设计 2026-10-23 4.7）", () => {
  const segments: ContextUsageData = {
    system: 3000,
    profile: 500,
    tools: 6000,
    related: 300,
    history: 10_200,
    total: 20_000,
    max_input_tokens: 200_000,
  };

  it("有 context.usage 事件时用它：占比按事件里的合计与上限算", () => {
    const state: ChatState = { ...chat(usage("u1", "main", 99_000)), context: segments };
    expect(contextView(state, 1_000_000)).toEqual({ label: "上下文 10%", usage: segments });
  });

  it("旧历史没有这个事件：退回最近一次主智能体调用的输入，没有分段", () => {
    expect(contextView(chat(usage("u1", "main", 21500)), 1_000_000)).toEqual({
      label: "上下文 2%",
      usage: null,
    });
    expect(contextView(chat(), 1_000_000)).toBeNull();
  });
});
