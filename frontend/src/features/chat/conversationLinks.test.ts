import { describe, expect, it } from "vitest";
import { conversationPath, conversationTarget, messageRunOf } from "./conversationLinks";

const T = "11111111-2222-3333-4444-555555555555";
const R = "66666666-7777-8888-9999-aaaaaaaaaaaa";

describe("会话链接（设计 2026-10-23 6.1）", () => {
  it("#conv-<会话 ID>-<运行 ID> 认得出两个编号；格式不对的不认", () => {
    expect(conversationTarget(`#conv-${T}-${R}`)).toEqual({ threadId: T, runId: R });
    expect(conversationTarget(`#conv-${T}`)).toBeNull();
    expect(conversationTarget("#kb-123")).toBeNull();
    expect(conversationTarget("https://example.com")).toBeNull();
    expect(conversationTarget(undefined)).toBeNull();
  });

  it("点开时去那个会话，带上是哪一轮", () => {
    expect(conversationPath({ threadId: T, runId: R })).toBe(`/chat/${T}?run=${R}`);
  });

  it("滚到那一轮：重试替换过的沿 retry_of 找到界面上那条用户消息所在的运行", () => {
    const runs = [
      { id: "a", retry_of: null },
      { id: "b", retry_of: "a" },
      { id: "c", retry_of: "b" },
    ];
    expect(messageRunOf("c", runs)).toBe("a");
    expect(messageRunOf("a", runs)).toBe("a");
    expect(messageRunOf("x", runs)).toBe("x");
    // 数据坏了成环也不会卡住
    expect(
      messageRunOf("p", [
        { id: "p", retry_of: "q" },
        { id: "q", retry_of: "p" },
      ]),
    ).toMatch(/p|q/);
  });
});
