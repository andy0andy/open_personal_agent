import { describe, expect, it } from "vitest";
import { formatSize } from "./format";

describe("文件大小的显示", () => {
  it("按 B / KB / MB / GB 换算，保留一位小数", () => {
    expect(formatSize(512)).toBe("512 B");
    expect(formatSize(2048)).toBe("2.0 KB");
    expect(formatSize(3.5 * 1024 * 1024)).toBe("3.5 MB");
    expect(formatSize(1.25 * 1024 ** 3)).toBe("1.3 GB");
  });
});
