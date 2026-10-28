import { describe, expect, it } from "vitest";
import type { DayUsage } from "../../api/types";
import { chartScale, callerLabel, fillDays, toolUsageLabel } from "./summary";

function day(date: string, calls: number): DayUsage {
  return {
    day: date,
    calls,
    input_tokens: calls * 100,
    output_tokens: calls * 10,
  };
}

describe("fillDays", () => {
  it("补齐开头、中间、结尾没有调用的日子", () => {
    const days = fillDays([day("2026-10-12", 2), day("2026-10-14", 1)], "2026-10-11", "2026-10-15");
    expect(days.map((d) => [d.day, d.calls])).toEqual([
      ["2026-10-11", 0],
      ["2026-10-12", 2],
      ["2026-10-13", 0],
      ["2026-10-14", 1],
      ["2026-10-15", 0],
    ]);
    // 只算 token（设计 2026-10-19 4.11）：补出来的日子只有调用次数、输入、输出
    expect(days[0]).toEqual({ day: "2026-10-11", calls: 0, input_tokens: 0, output_tokens: 0 });
  });
  it("只有一天", () => {
    expect(fillDays([], "2026-10-16", "2026-10-16").map((d) => d.day)).toEqual(["2026-10-16"]);
  });
  it("跨月", () => {
    expect(fillDays([], "2026-10-30", "2026-11-02").map((d) => d.day)).toEqual([
      "2026-10-30",
      "2026-10-31",
      "2026-11-01",
      "2026-11-02",
    ]);
  });
});

describe("callerLabel", () => {
  it("调用方的中文名", () => {
    expect(callerLabel("main")).toBe("主智能体");
    expect(callerLabel("compaction")).toBe("上下文压缩");
    expect(callerLabel("title")).toBe("生成标题");
    expect(callerLabel("memory_extraction")).toBe("整理记忆");
    expect(callerLabel("embedding")).toBe("向量化");
    expect(callerLabel("data_analyst")).toBe("子智能体 data_analyst");
  });
});

describe("每日柱状图的刻度", () => {
  it("顶端取 1.5、3、6 × 10ⁿ 里不小于最大值的最小者：四条刻度都是整数", () => {
    expect(chartScale([434000, 12000])).toEqual({
      max: 600000,
      ticks: [600000, 400000, 200000, 0],
    });
    expect(chartScale([1200000]).max).toBe(1500000);
    expect(chartScale([3000]).max).toBe(3000);
    expect(chartScale([2]).ticks).toEqual([3, 2, 1, 0]);
  });

  it("全为 0 或没有数据：刻度照样画得出来", () => {
    expect(chartScale([0, 0])).toEqual({ max: 3, ticks: [3, 2, 1, 0] });
    expect(chartScale([]).max).toBe(3);
  });
});

describe("工具用量里的工具名（设计 2026-10-23 6.8）", () => {
  it("内置工具用中文名，MCP 工具写服务与工具，不认识的照原名", () => {
    expect(toolUsageLabel("read_file")).toBe("读取文件");
    expect(toolUsageLabel("files_read_file")).toBe("外部工具 · files · read_file");
    expect(toolUsageLabel("Mystery")).toBe("Mystery");
  });
});
