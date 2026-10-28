import { ensureToken, refreshToken } from "./session";
import type { EventEnvelope } from "./types";

/**
 * 订阅一次运行的推送，从第 afterSeq 个事件之后开始（之前的已从界面历史显示）；
 * 收到 run.finished（运行结束）或 approval.required（停下等审批）后主动关闭，避免浏览器自动重连。
 *
 * 推送带不了请求头，靠取令牌时下发的 Cookie（D25）：先确保取过令牌再打开。被服务器关掉时
 * （如后端重启、令牌换了，浏览器不会再自动重连）重取令牌，从最后收到的序号重开一次。
 */
export function subscribeRun(
  runId: string,
  afterSeq: number,
  onEvent: (event: EventEnvelope) => void,
): () => void {
  let source: EventSource | null = null;
  let last = afterSeq;
  let stopped = false;
  let reopened = false;

  const stop = () => {
    stopped = true;
    source?.close();
  };
  const open = () => {
    if (stopped) return;
    const current = new EventSource(`/api/runs/${runId}/events?after=${last}`);
    source = current;
    current.onmessage = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as EventEnvelope;
      last = event.seq;
      onEvent(event);
      if (event.type === "run.finished" || event.type === "approval.required") stop();
    };
    current.onerror = () => {
      if (stopped || reopened || current.readyState !== EventSource.CLOSED) return;
      reopened = true;
      void refreshToken().then(open, open);
    };
  };
  // 取不到令牌也照样打开：被拒后由上面的 onerror 再重取一次
  void ensureToken().then(open, open);
  return stop;
}
