import { afterEach, describe, expect, it, vi } from "vitest";
import { TITLE_REFRESH_DELAYS, isAutoTitle, scheduleRefreshes } from "./titleRefresh";

describe("isAutoTitle", () => {
  it("标题还是首条消息的前 30 个字（按字符算，表情也算一个字）", () => {
    const message = "帮我写一个每周给团队发的周报模板😀，要包含本周进展、风险和下周计划";
    expect(isAutoTitle(Array.from(message).slice(0, 30).join(""), message)).toBe(true);
    expect(isAutoTitle("周报模板", message)).toBe(false);
    expect(isAutoTitle("", "")).toBe(false); // 还没有消息
  });
});

describe("scheduleRefreshes", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("按给定的间隔依次刷新，取消后不再刷新", () => {
    vi.useFakeTimers();
    const refresh = vi.fn();
    const cancel = scheduleRefreshes(refresh, [1000, 3000, 6000]);
    vi.advanceTimersByTime(1000);
    expect(refresh).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(2000);
    expect(refresh).toHaveBeenCalledTimes(2);
    cancel();
    vi.advanceTimersByTime(10000);
    expect(refresh).toHaveBeenCalledTimes(2);
  });
});

describe("标题生成排在别的后台任务后面时（积压小问题 B2）", () => {
  it("刷新一直持续到 60 秒，不在 20 秒就停", () => {
    expect(Math.max(...TITLE_REFRESH_DELAYS)).toBeGreaterThanOrEqual(60_000);
  });
});
