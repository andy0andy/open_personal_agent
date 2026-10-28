import { describe, expect, it } from "vitest";
import { SEARCH_DELAY_MS, extraTitleMatches, highlightParts, hitLink, queryWords } from "./search";

describe("会话搜索（设计 2026-10-23 6.1）", () => {
  it("停顿 300 毫秒后才查内容", () => {
    expect(SEARCH_DELAY_MS).toBe(300);
  });

  it("片段里的命中词单独切出来加粗：不分大小写、多个词都算、正则符号按字面", () => {
    expect(highlightParts("…想去香格里拉玩…", queryWords("香格里拉"))).toEqual([
      { text: "…想去", hit: false },
      { text: "香格里拉", hit: true },
      { text: "玩…", hit: false },
    ]);
    expect(highlightParts("Hello world, hello", queryWords("HELLO"))).toEqual([
      { text: "Hello", hit: true },
      { text: " world, ", hit: false },
      { text: "hello", hit: true },
    ]);
    expect(highlightParts("大理和丽江", queryWords("丽江 大理"))).toEqual([
      { text: "大理", hit: true },
      { text: "和", hit: false },
      { text: "丽江", hit: true },
    ]);
    expect(highlightParts("a.b", queryWords("."))).toEqual([
      { text: "a", hit: false },
      { text: ".", hit: true },
      { text: "b", hit: false },
    ]);
    expect(highlightParts("没有命中", queryWords("香格里拉"))).toEqual([
      { text: "没有命中", hit: false },
    ]);
  });

  it("标题匹配：服务器找到的（如已归档的）只补本地即时过滤里没有的", () => {
    const local = [{ id: "a", title: "云南旅行" }];
    const server = [
      { id: "a", title: "云南旅行" },
      { id: "b", title: "云南美食" },
    ];
    expect(extraTitleMatches(local, server).map((thread) => thread.id)).toEqual(["b"]);
  });

  it("点内容里的结果：打开那个会话，带上是哪一轮", () => {
    expect(hitLink({ thread_id: "t1", run_id: "r1" })).toBe("/chat/t1?run=r1");
  });
});

describe("按服务器给的命中词加粗（积压小问题 B4）", () => {
  it("搜“上海天气”命中“上海的天气”：两个词都加粗", () => {
    expect(highlightParts("上海的天气怎么样", ["上海天气", "上海", "天气"])).toEqual([
      { text: "上海", hit: true },
      { text: "的", hit: false },
      { text: "天气", hit: true },
      { text: "怎么样", hit: false },
    ]);
  });
});
