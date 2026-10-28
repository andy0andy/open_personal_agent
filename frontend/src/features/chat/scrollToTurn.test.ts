import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { keepScrolledTo } from "./scrollToTurn";

/** 假的那一轮：top 是它离视口顶部的距离；scrollIntoView 时数一次并把它挪进视口。 */
function fakeTurn(top: number) {
  const turn = {
    top,
    scrolled: 0,
    getBoundingClientRect: () => ({ top: turn.top }),
    scrollIntoView: () => {
      turn.scrolled += 1;
      turn.top = 300;
    },
  };
  return turn;
}

describe("打开会话时滚到要看的那一轮（8000 实测：长对话渲染慢，滚过去会被“自动滚到底”盖掉）", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("window", new EventTarget()); // 单测跑在 node 里：只要能收发事件
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("被自动滚到底盖掉了就再滚过去，连续两次都在视口里就停", () => {
    const turn = fakeTurn(-9000);
    keepScrolledTo(() => turn as unknown as Element, 768);
    vi.advanceTimersByTime(200);
    expect(turn.scrolled).toBe(1);
    turn.top = -9000; // 对话区渲染完又滚到了底
    vi.advanceTimersByTime(200);
    expect(turn.scrolled).toBe(2);
    vi.advanceTimersByTime(2000);
    expect(turn.scrolled).toBe(2);
  });

  it("那一轮渲染得慢就接着等；出现以后再管 3 秒（后端刚重启时第一次打开很慢）", () => {
    let turn: ReturnType<typeof fakeTurn> | null = null;
    keepScrolledTo(() => turn as unknown as Element | null, 768);
    vi.advanceTimersByTime(5000);
    const stuck = fakeTurn(-5000);
    stuck.scrollIntoView = () => {
      stuck.scrolled += 1; // 一直滚不过去
    };
    turn = stuck;
    vi.advanceTimersByTime(3400); // 第一次看到它要等下一次检查，再管 3 秒
    const count = stuck.scrolled;
    expect(count).toBeGreaterThan(0);
    vi.advanceTimersByTime(2000);
    expect(stuck.scrolled).toBe(count);
  });

  it("那一轮一直没出现：等 10 秒就不再等", () => {
    let turn: ReturnType<typeof fakeTurn> | null = null;
    keepScrolledTo(() => turn as unknown as Element | null, 768);
    vi.advanceTimersByTime(10_400);
    const late = fakeTurn(-5000);
    turn = late;
    vi.advanceTimersByTime(1000);
    expect(late.scrolled).toBe(0);
  });

  it("用户自己动了滚轮就不再管", () => {
    const turn = fakeTurn(-9000);
    keepScrolledTo(() => turn as unknown as Element, 768);
    vi.advanceTimersByTime(200);
    window.dispatchEvent(new Event("wheel"));
    turn.top = -9000;
    vi.advanceTimersByTime(1000);
    expect(turn.scrolled).toBe(1);
  });

  it("离开页面时停下", () => {
    const turn = fakeTurn(-9000);
    const stop = keepScrolledTo(() => turn as unknown as Element, 768);
    stop();
    vi.advanceTimersByTime(1000);
    expect(turn.scrolled).toBe(0);
  });
});
