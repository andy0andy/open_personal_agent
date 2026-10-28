import type { Thread } from "../../api/types";

export interface ThreadActivityView {
  tone: "info" | "warning" | "danger" | "success";
  label: "运行中" | "待审批" | "出错" | "有新回答";
  pulse: boolean;
}

const VIEWS: Record<NonNullable<Thread["activity"]>, ThreadActivityView> = {
  running: { tone: "info", label: "运行中", pulse: true },
  waiting: { tone: "warning", label: "待审批", pulse: false },
  failed: { tone: "danger", label: "出错", pulse: false },
  // 顺利结束、你还没看（设计 2026-10-23 6.5）
  new: { tone: "success", label: "有新回答", pulse: false },
};

/** 会话列表的状态点（设计 2026-10-22 3.1）；空闲时不显示。 */
export function threadActivity(thread: Pick<Thread, "activity">): ThreadActivityView | null {
  return thread.activity ? VIEWS[thread.activity] : null;
}

/** 会话列表底部的"已归档（N）"（设计 2026-10-23 6.5）；没有归档的会话时不显示。 */
export function archivedLabel(count: number): string | null {
  return count > 0 ? `已归档（${count}）` : null;
}

/** 有会话在跑或在等审批：会话列表要定时刷新，状态点才会跟着变。 */
export function hasActiveThread(threads?: Pick<Thread, "activity">[]): boolean {
  return (threads ?? []).some(
    (thread) => thread.activity === "running" || thread.activity === "waiting",
  );
}

const sameDay = (a: Date, b: Date) =>
  a.getFullYear() === b.getFullYear() &&
  a.getMonth() === b.getMonth() &&
  a.getDate() === b.getDate();

/** 会话列表右侧的时间：今天 HH:MM、昨天、今年 M月D日、更早 YYYY/M/D（按本机时区）。 */
export function relativeTime(iso: string, now: Date): string {
  const time = new Date(iso);
  if (Number.isNaN(time.getTime())) return "";
  if (sameDay(time, now)) {
    const pad = (value: number) => String(value).padStart(2, "0");
    return `${pad(time.getHours())}:${pad(time.getMinutes())}`;
  }
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (sameDay(time, yesterday)) return "昨天";
  if (time.getFullYear() === now.getFullYear()) {
    return `${time.getMonth() + 1}月${time.getDate()}日`;
  }
  return `${time.getFullYear()}/${time.getMonth() + 1}/${time.getDate()}`;
}

/** 按标题过滤（不分大小写）；没有标题的会话按显示出来的"新会话"匹配。空查询原样返回。 */
export function filterThreads<T extends { title: string }>(threads: T[], query: string): T[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return threads;
  return threads.filter((thread) => (thread.title || "新会话").toLowerCase().includes(needle));
}
