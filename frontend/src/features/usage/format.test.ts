import { describe, expect, it } from "vitest";
import { formatDuration, formatElapsed, formatTokens } from "./format";

describe("用量数字的显示", () => {
  it("token 数超过一千用 k、超过一百万用 M，保留一位小数", () => {
    expect(formatTokens(999)).toBe("999");
    expect(formatTokens(4629)).toBe("4.6k");
    expect(formatTokens(12_000)).toBe("12k");
    expect(formatTokens(1_250_000)).toBe("1.3M");
  });
});

describe("耗时的显示", () => {
  it("完成后：一分钟内保留一位小数，之后用分秒、小时分", () => {
    expect(formatDuration(500)).toBe("0.5 秒");
    expect(formatDuration(23_400)).toBe("23.4 秒");
    expect(formatDuration(192_000)).toBe("3 分 12 秒");
    expect(formatDuration(3_725_000)).toBe("1 小时 2 分");
  });

  it("运行中：按整秒显示", () => {
    expect(formatElapsed(12_900)).toBe("12 秒");
    expect(formatElapsed(65_000)).toBe("1 分 5 秒");
  });
});
