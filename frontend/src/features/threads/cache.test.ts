import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { archivedThreadsQuery, threadQuery, threadsQuery } from "../../api/queries";
import type { Thread } from "../../api/types";
import { addCreatedThread, forgetThread, replaceThread } from "./cache";

const thread = (id: string) => ({ id, title: id }) as unknown as Thread;

describe("新建的会话放进会话列表", () => {
  it("恰好有一次列表刷新还没返回时，旧列表不会把新会话盖掉", async () => {
    vi.useFakeTimers();
    try {
      const client = new QueryClient();
      const key = threadsQuery.queryKey;
      client.setQueryData<Thread[]>(key, [thread("old")]);
      // 刷新在新建之前发出，返回的是还没有新会话的旧列表（20 毫秒后才回来）
      const refresh = client
        .fetchQuery({
          queryKey: key,
          queryFn: () =>
            new Promise<Thread[]>((resolve) => setTimeout(() => resolve([thread("old")]), 20)), // 允许等待：替身模拟请求慢（假时钟推进）
        })
        .catch(() => undefined);
      await addCreatedThread(client, thread("new"));
      await refresh;
      await vi.advanceTimersByTimeAsync(40); // 那次刷新回来了
      expect(client.getQueryData<Thread[]>(key)?.map((item) => item.id)).toEqual(["new", "old"]);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("改了会话的标题或设置后更新列表", () => {
  it("保留列表里的运行状态：其他接口不带状态，直接替换会让状态点闪掉", async () => {
    const client = new QueryClient();
    const key = threadsQuery.queryKey;
    client.setQueryData<Thread[]>(key, [{ ...thread("a"), activity: "running" }, thread("b")]);
    await replaceThread(client, { ...thread("a"), title: "新标题", activity: null });
    expect(client.getQueryData<Thread[]>(key)).toEqual([
      { ...thread("a"), title: "新标题", activity: "running" },
      thread("b"),
    ]);
  });
});

describe("删掉的会话（审查 I3：在已归档的会话里删除它，页面不走、归档列表不更新）", () => {
  it("从列表移除；按 ID 取的那份与归档列表都要重新查", () => {
    const client = new QueryClient();
    client.setQueryData<Thread[]>(threadsQuery.queryKey, [thread("a"), thread("b")]);
    client.setQueryData(threadQuery("b").queryKey, thread("b"));
    client.setQueryData<Thread[]>(archivedThreadsQuery.queryKey, [thread("b")]);
    forgetThread(client, "b");
    expect(client.getQueryData<Thread[]>(threadsQuery.queryKey)?.map((item) => item.id)).toEqual([
      "a",
    ]);
    expect(client.getQueryState(threadQuery("b").queryKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(archivedThreadsQuery.queryKey)?.isInvalidated).toBe(true);
  });
});

describe("改了会话设置时恰好有一次列表刷新没回来（积压小问题 B5）", () => {
  it("那次刷新晚到也不会把旧模型写回", async () => {
    vi.useFakeTimers();
    try {
      const client = new QueryClient();
      const key = threadsQuery.queryKey;
      const old = { ...thread("a"), model: "old-model" } as Thread;
      client.setQueryData<Thread[]>(key, [old]);
      const refresh = client
        .fetchQuery({
          queryKey: key,
          queryFn: () => new Promise<Thread[]>((resolve) => setTimeout(() => resolve([old]), 20)), // 允许等待：替身模拟请求慢（假时钟推进）
        })
        .catch(() => undefined);
      await replaceThread(client, { ...old, model: "new-model" } as Thread);
      await vi.advanceTimersByTimeAsync(40); // 那次刷新回来了（没取消的话会带回旧模型）
      await refresh;
      expect(client.getQueryData<Thread[]>(key)?.[0]?.model).toBe("new-model");
    } finally {
      vi.useRealTimers();
    }
  });
});
