import { describe, expect, it } from "vitest";
import { createSaveQueue } from "./saveQueue";

function deferred(): { promise: Promise<void>; resolve: () => void; reject: (e: Error) => void } {
  let resolve!: () => void;
  let reject!: (e: Error) => void;
  const promise = new Promise<void>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const flush = async (): Promise<void> => {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
};

describe("会话设置的保存排队", () => {
  it("保存进行中时 idle() 要等它完成", async () => {
    const queue = createSaveQueue();
    const save = deferred();
    void queue.run(() => save.promise);
    let done = false;
    const idle = queue.idle().then((ok) => {
      done = true;
      return ok;
    });
    await flush();
    expect(done).toBe(false);
    save.resolve();
    expect(await idle).toBe(true);
  });

  it("等着的那次保存失败时 idle() 为 false（这条消息不发）", async () => {
    const queue = createSaveQueue();
    const save = deferred();
    queue.run(() => save.promise).catch(() => {});
    const idle = queue.idle();
    save.reject(new Error("网关不可用"));
    expect(await idle).toBe(false);
  });

  it("失败已经过去（已提示并恢复原值）时不挡之后的发送；再成功一次也为 true", async () => {
    const queue = createSaveQueue();
    await queue.run(() => Promise.reject(new Error("x"))).catch(() => {});
    expect(await queue.idle()).toBe(true);
    await queue.run(() => Promise.resolve());
    expect(await queue.idle()).toBe(true);
  });

  it("按顺序保存：后一次在前一次结束后才开始", async () => {
    const queue = createSaveQueue();
    const order: string[] = [];
    const first = deferred();
    void queue.run(async () => {
      await first.promise;
      order.push("first");
    });
    void queue.run(async () => {
      order.push("second");
    });
    await flush();
    expect(order).toEqual([]);
    first.resolve();
    await queue.idle();
    expect(order).toEqual(["first", "second"]);
  });
});
