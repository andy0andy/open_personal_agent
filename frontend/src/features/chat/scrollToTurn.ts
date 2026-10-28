const CHECK_MS = 200; // 每隔多久看一次
const WAIT_MS = 10_000; // 那一轮最多等多久才渲染出来（后端刚重启时第一次打开很慢）
const GIVE_UP_MS = 3000; // 那一轮出现以后最多管多久
const STABLE_CHECKS = 2; // 连续几次都在视口里就算停稳了
// 用户自己动了：不再替他滚
const USER_EVENTS = ["wheel", "touchstart", "keydown", "mousedown"] as const;

/**
 * 打开会话时滚到要看的那一轮（设计 2026-10-23 6.1）：长对话渲染、对话区"自动滚到底"都要一会儿，
 * 一次滚过去会被盖掉（8000 上实测）。每隔一会儿看一次，不在视口里就再滚过去；连续两次都在就停，
 * 那一轮出现以后最多管 3 秒（最多等它出现 10 秒）；用户自己滚动、按键就不再管。
 * 返回停止函数（离开页面时调用）。
 */
export function keepScrolledTo(find: () => Element | null, viewportHeight: number): () => void {
  const started = Date.now();
  let seen: number | null = null; // 那一轮第一次出现的时间
  let stable = 0;
  const stop = (): void => {
    clearInterval(timer);
    for (const name of USER_EVENTS) window.removeEventListener(name, stop);
  };
  const timer = setInterval(() => {
    const now = Date.now();
    const turn = find();
    if (!turn) {
      if (now - started > WAIT_MS) stop();
      return;
    }
    seen ??= now;
    if (now - seen > GIVE_UP_MS) return stop();
    const { top } = turn.getBoundingClientRect();
    if (top >= 0 && top < viewportHeight) {
      stable += 1;
      if (stable >= STABLE_CHECKS) stop();
      return;
    }
    stable = 0;
    turn.scrollIntoView({ block: "center" });
  }, CHECK_MS);
  for (const name of USER_EVENTS) window.addEventListener(name, stop, { passive: true });
  return stop;
}
