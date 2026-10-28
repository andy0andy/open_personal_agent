import { MutationObserver, QueryClient, QueryObserver } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { threadsQuery } from "../../api/queries";
import { pendingOrder } from "./order";
import { reorderMutation } from "./reorder";

type Row = { id: string };
const key = threadsQuery.queryKey;

afterEach(() => {
  vi.useRealTimers();
});

describe("拖动排序的保存（积压小问题 B1）", () => {
  it("保存期间轮询带回旧顺序：保存结束到刷新回来之间也不闪回旧顺序（审查 Minor 2）", async () => {
    vi.useFakeTimers();
    const client = new QueryClient();
    let server: Row[] = [{ id: "a" }, { id: "b" }, { id: "c" }];
    // 请求到达服务器时读到的顺序，10 毫秒后返回
    const fetchList = () =>
      new Promise<Row[]>((resolve) => {
        const snapshot = server;
        setTimeout(() => resolve(snapshot), 10); // 允许等待：假时钟下模拟网络
      });
    client.setQueryData(key, server);
    new QueryObserver(client, { queryKey: key, queryFn: fetchList, staleTime: Infinity }).subscribe(
      () => undefined,
    );
    // 50 毫秒后服务器才换成新顺序
    const save = (ids: string[]) =>
      new Promise<void>((resolve) => {
        setTimeout(() => {
          server = ids.map((id) => ({ id }));
          resolve();
        }, 50); // 允许等待：假时钟下模拟保存慢
      });
    const mutation = new MutationObserver<unknown, Error, string[]>(
      client,
      reorderMutation(client, save),
    );
    const shown: string[] = [];
    const record = () => {
      const state = mutation.getCurrentResult();
      const cache = client.getQueryData<Row[]>(key) ?? [];
      const list =
        state.isPending && state.variables ? pendingOrder(cache, state.variables) : cache;
      shown.push(list.map((row) => row.id).join(""));
    };
    mutation.subscribe(record);
    client.getQueryCache().subscribe(record);

    client.setQueryData(key, [{ id: "c" }, { id: "a" }, { id: "b" }]); // 拖完：界面先排好
    void mutation.mutate(["c", "a", "b"]).catch(() => undefined);
    await vi.advanceTimersByTimeAsync(5);
    void client.refetchQueries({ queryKey: key }); // 保存还没回来时轮询发出，带回旧顺序
    await vi.advanceTimersByTimeAsync(200);

    expect(shown.filter((order) => order === "abc")).toEqual([]);
    expect(shown.at(-1)).toBe("cab");
  });
});
