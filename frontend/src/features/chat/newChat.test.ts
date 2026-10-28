import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { threadsQuery } from "../../api/queries";
import type { Thread, ThreadCreated } from "../../api/types";
import { rememberNewThread, startNewChat } from "./newChat";

const created = {
  id: "t1",
  model: "default-model",
  permission_mode: "ask",
  run: null,
} as ThreadCreated;

function fakeDeps(options: { fail?: boolean } = {}) {
  const calls: unknown[] = [];
  return {
    calls,
    deps: {
      createThread: async (input: Record<string, unknown>) => {
        calls.push(input);
        if (options.fail) throw new Error("模型不存在：other");
        return { ...created, ...input } as ThreadCreated;
      },
    },
  };
}

describe("落地页发第一条消息（建会话一次完成，设计 2026-10-23 6.4）", () => {
  it("一次请求：带上消息、所选的模型与权限", async () => {
    const { calls, deps } = fakeDeps();
    const thread = await startNewChat({ text: "你好", model: "other", permission: "skip" }, deps);
    expect(calls).toEqual([{ message: "你好", model: "other", permission_mode: "skip" }]);
    expect(thread.id).toBe("t1");
  });

  it("模型列表还没加载（没选模型）：不带模型，用新会话的默认模型", async () => {
    const { calls, deps } = fakeDeps();
    await startNewChat({ text: "你好", model: "", permission: "ask" }, deps);
    expect(calls).toEqual([{ message: "你好", permission_mode: "ask" }]);
  });

  it("失败时抛出：后端不留空会话，字留在落地页", async () => {
    const { deps } = fakeDeps({ fail: true });
    await expect(
      startNewChat({ text: "你好", model: "other", permission: "ask" }, deps),
    ).rejects.toThrow("模型不存在：other");
  });
});

describe("落地页建好会话以后", () => {
  it("放进会话列表，并让列表马上刷新：标题与运行中的状态点由列表接口算", async () => {
    const client = new QueryClient();
    client.setQueryData(threadsQuery.queryKey, [{ id: "old" }]);
    await rememberNewThread(client, created);
    expect(client.getQueryData<Thread[]>(threadsQuery.queryKey)?.map((t) => t.id)).toEqual([
      "t1",
      "old",
    ]);
    expect(client.getQueryState(threadsQuery.queryKey)?.isInvalidated).toBe(true);
  });
});
