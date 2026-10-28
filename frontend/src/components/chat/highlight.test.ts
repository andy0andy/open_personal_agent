import { describe, expect, it } from "vitest";
import { highlight } from "./highlight";

describe("highlight：代码着色", () => {
  it("认得的语言：返回带 hljs 类名的片段", () => {
    const tree = highlight("def add(a, b):\n    return a + b", "python");
    expect(JSON.stringify(tree)).toContain("hljs-keyword");
  });

  it("语言名不分大小写，常见简称也认得", () => {
    expect(highlight("const x: number = 1", "TS")).not.toBeNull();
    expect(highlight("x = 1", "py")).not.toBeNull();
    expect(highlight("echo hi", "sh")).not.toBeNull();
  });

  it("不认得的语言或没写语言：返回 null（照原样显示）", () => {
    expect(highlight("x", "klingon")).toBeNull();
    expect(highlight("x", "")).toBeNull();
  });
});
