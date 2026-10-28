import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ContextMeter } from "./ContextMeter";

describe("上下文分段条（设计 2026-10-23 4.7）", () => {
  const usage = {
    system: 3000,
    profile: 500,
    tools: 6000,
    related: 300,
    history: 10_200,
    total: 20_000,
    max_input_tokens: 200_000,
  };

  it("显示占比，展开后列出五个部分各自的大小与占比", () => {
    const html = renderToStaticMarkup(<ContextMeter label="上下文 10%" usage={usage} />);
    expect(html).toContain("上下文 10%");
    for (const name of ["系统提示词", "常驻记忆", "工具定义", "相关记忆", "对话历史"]) {
      expect(html).toContain(name);
    }
    expect(html).toContain("51%"); // 对话历史 10200 / 20000
    expect(html).toContain("6k");
  });

  it("旧历史没有分段：只显示占比", () => {
    const html = renderToStaticMarkup(<ContextMeter label="上下文 2%" usage={null} />);
    expect(html).toContain("上下文 2%");
    expect(html).not.toContain("系统提示词");
  });
});
