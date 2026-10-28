import { describe, expect, it } from "vitest";
import { createGuard } from "./guard";

describe("同一时间只跑一个（连点“重试这一轮”只发一次请求）", () => {
  it("上一个还没结束时再调用直接忽略；结束后可以再跑", async () => {
    const guard = createGuard();
    let calls = 0;
    let finish: () => void = () => {};
    const task = () =>
      new Promise<void>((resolve) => {
        calls += 1;
        finish = resolve;
      });
    const first = guard.run(task);
    await guard.run(task); // 第一个还在跑：忽略
    expect(calls).toBe(1);
    finish();
    await first;
    const again = guard.run(task);
    expect(calls).toBe(2);
    finish();
    await again;
  });

  it("出错后也放开", async () => {
    const guard = createGuard();
    await expect(guard.run(() => Promise.reject(new Error("409")))).rejects.toThrow("409");
    let ran = false;
    await guard.run(async () => {
      ran = true;
    });
    expect(ran).toBe(true);
  });
});
