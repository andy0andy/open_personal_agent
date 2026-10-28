import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { subscribeRun } from "./events";
import { ensureToken, refreshToken } from "./session";

vi.mock("./session", () => ({
  ensureToken: vi.fn(async () => "t1"),
  refreshToken: vi.fn(async () => "t2"),
}));

/** 假的 EventSource：记下打开的地址；测试里手动推消息、模拟被服务器关掉。 */
class FakeSource {
  static CLOSED = 2;
  static opened: FakeSource[] = [];
  onmessage: ((m: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  closed = false;
  constructor(readonly url: string) {
    FakeSource.opened.push(this);
  }
  close() {
    this.closed = true;
    this.readyState = FakeSource.CLOSED;
  }
  push(event: object) {
    this.onmessage?.({ data: JSON.stringify(event) });
  }
  /** 服务器拒绝或断开且不再重连（如后端重启后令牌对不上）。 */
  fail() {
    this.readyState = FakeSource.CLOSED;
    this.onerror?.();
  }
}

const urls = () => FakeSource.opened.map((source) => source.url);

describe("subscribeRun", () => {
  beforeEach(() => {
    vi.useFakeTimers(); // 不靠固定等待（设计 2026-10-23 7.6）
    FakeSource.opened = [];
    vi.stubGlobal("EventSource", FakeSource);
    vi.mocked(refreshToken).mockClear();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("先取令牌（同时拿到 Cookie），再从已显示的最后一个事件之后订阅", async () => {
    const stop = subscribeRun("r1", 4, () => undefined);
    expect(ensureToken).toHaveBeenCalled();
    await vi.waitFor(() => expect(urls()).toEqual(["/api/runs/r1/events?after=4"]));
    stop();
  });

  it("收到 approval.required 后关闭：运行在等审批，没有后续推送", async () => {
    subscribeRun("r1", 0, () => undefined);
    await vi.waitFor(() => expect(FakeSource.opened).toHaveLength(1));
    const [source] = FakeSource.opened;
    source?.push({ type: "approval.required", seq: 3 });
    expect(source?.closed).toBe(true);
  });

  it("被服务器关掉时重取令牌，从最后收到的序号重开一次；再被关掉就不再重开", async () => {
    const seen: number[] = [];
    subscribeRun("r1", 2, (event) => seen.push(event.seq));
    await vi.waitFor(() => expect(FakeSource.opened).toHaveLength(1));
    FakeSource.opened[0]?.push({ type: "message.delta", seq: 3 });
    FakeSource.opened[0]?.fail();
    await vi.waitFor(() => expect(FakeSource.opened).toHaveLength(2));
    expect(refreshToken).toHaveBeenCalledTimes(1);
    expect(urls()[1]).toBe("/api/runs/r1/events?after=3");
    FakeSource.opened[1]?.push({ type: "message.delta", seq: 4 });
    FakeSource.opened[1]?.fail();
    await vi.runAllTimersAsync(); // 把已排上的事都做完，再看有没有又打开
    expect(FakeSource.opened).toHaveLength(2);
    expect(seen).toEqual([3, 4]);
  });

  it("停止订阅后不再打开", async () => {
    const stop = subscribeRun("r1", 0, () => undefined);
    stop();
    await vi.runAllTimersAsync(); // 取令牌那一步做完，再看有没有打开
    expect(FakeSource.opened).toHaveLength(0);
  });
});
