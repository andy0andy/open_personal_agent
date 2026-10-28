import { describe, expect, it } from "vitest";
import type { Thread } from "../../api/types";
import {
  archivedLabel,
  filterThreads,
  hasActiveThread,
  relativeTime,
  threadActivity,
} from "./activity";

describe("会话状态点", () => {
  it("运行中是蓝色呼吸点，待审批琥珀，出错红色", () => {
    expect(threadActivity({ activity: "running" })).toEqual({
      tone: "info",
      label: "运行中",
      pulse: true,
    });
    expect(threadActivity({ activity: "waiting" })).toEqual({
      tone: "warning",
      label: "待审批",
      pulse: false,
    });
    expect(threadActivity({ activity: "failed" })).toEqual({
      tone: "danger",
      label: "出错",
      pulse: false,
    });
  });

  it("顺利结束、还没看过：绿点“有新回答”（设计 2026-10-23 6.5）", () => {
    expect(threadActivity({ activity: "new" })).toEqual({
      tone: "success",
      label: "有新回答",
      pulse: false,
    });
  });

  it("空闲、或接口没带这个字段：不显示", () => {
    expect(threadActivity({ activity: null })).toBeNull();
    expect(threadActivity({})).toBeNull();
  });
});

describe("相对时间", () => {
  const now = new Date(2026, 9, 22, 14, 30);
  const at = (...parts: [number, number, number, number, number?]) =>
    new Date(...parts).toISOString();

  it("今天显示时分", () => {
    expect(relativeTime(at(2026, 9, 22, 9, 5), now)).toBe("09:05");
  });

  it("昨天", () => {
    expect(relativeTime(at(2026, 9, 21, 23, 59), now)).toBe("昨天");
    // 跨年的昨天也是"昨天"
    expect(relativeTime(at(2025, 11, 31, 22), new Date(2026, 0, 1, 10))).toBe("昨天");
  });

  it("今年更早显示月日，往年显示年月日", () => {
    expect(relativeTime(at(2026, 0, 3, 8), now)).toBe("1月3日");
    expect(relativeTime(at(2025, 11, 31, 8), now)).toBe("2025/12/31");
  });

  it("看不懂的时间不显示", () => {
    expect(relativeTime("not a date", now)).toBe("");
  });
});

describe("按标题搜索会话", () => {
  const list = [{ title: "分析 Sales 表" }, { title: "读书笔记" }, { title: "" }];

  it("空查询原样返回", () => {
    expect(filterThreads(list, "  ")).toBe(list);
  });

  it("不分大小写，去掉首尾空白", () => {
    expect(filterThreads(list, " sales ")).toEqual([list[0]]);
  });

  it("没有标题的会话按显示出来的“新会话”匹配", () => {
    expect(filterThreads(list, "新会话")).toEqual([list[2]]);
  });
});

describe("会话列表要不要定时刷新", () => {
  const threads = (...activity: Thread["activity"][]) =>
    activity.map((value) => ({ activity: value })) as Thread[];

  it("有会话在跑或在等审批时才刷新", () => {
    expect(hasActiveThread(undefined)).toBe(false);
    expect(hasActiveThread(threads(null, "failed"))).toBe(false);
    expect(hasActiveThread(threads(null, "waiting"))).toBe(true);
    expect(hasActiveThread(threads("running"))).toBe(true);
  });
});

describe("已归档（设计 2026-10-23 6.5）", () => {
  it("列表底部写“已归档（N）”；没有归档的会话时不显示", () => {
    expect(archivedLabel(3)).toBe("已归档（3）");
    expect(archivedLabel(0)).toBeNull();
  });
});
