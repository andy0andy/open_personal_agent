import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CountTable } from "./CountTable";

describe("工具与技能用量表（设计 2026-10-23 6.8）", () => {
  it("名称与次数，按给的顺序（后端已按次数从多到少排好）", () => {
    const html = renderToStaticMarkup(
      <CountTable
        title="工具"
        rows={[
          { key: "read_file", label: "读取文件", count: 2 },
          { key: "ls", label: "列出目录", count: 1 },
        ]}
      />,
    );
    expect(html).toContain("工具");
    expect(html).toContain("次数");
    expect(html.indexOf("读取文件")).toBeLessThan(html.indexOf("列出目录"));
  });

  it("这段时间没有时照样显示这张表，写明没有", () => {
    const html = renderToStaticMarkup(<CountTable title="技能" rows={[]} />);
    expect(html).toContain("技能");
    expect(html).toContain("这段时间没有");
  });
});
