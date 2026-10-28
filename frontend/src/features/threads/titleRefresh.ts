/**
 * 会话第一次顺利结束后，后台按对话内容生成标题（通常几秒内完成）：
 * 期间隔一阵刷新几次会话列表，标题出来后侧栏与顶部自动更新。后台任务一次只做一个，
 * 前面排着别的会话的记忆提取时标题会晚一些，所以一直看到 1 分钟。
 */
export const TITLE_REFRESH_DELAYS = [2000, 5000, 10000, 20000, 30000, 45000, 60000];

/** 标题还是自动标题：首条消息的前 30 个字（与后端一致，按字符而不是 UTF-16 单元算）。 */
export function isAutoTitle(title: string, firstMessage: string): boolean {
  return firstMessage !== "" && title === Array.from(firstMessage).slice(0, 30).join("");
}

/** 按给定的间隔（从现在算起）依次调用 refresh；返回取消函数。 */
export function scheduleRefreshes(
  refresh: () => void,
  delays: number[] = TITLE_REFRESH_DELAYS,
): () => void {
  const timers = delays.map((delay) => setTimeout(refresh, delay));
  return () => timers.forEach(clearTimeout);
}
