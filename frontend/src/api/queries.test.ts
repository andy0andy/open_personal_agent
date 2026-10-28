import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./client";
import {
  historyQuery,
  knowledgeQuery,
  modelsQuery,
  refreshKnowledge,
  retryWhileFailing,
  threadsQuery,
} from "./queries";

describe("historyQuery", () => {
  it("离开会话后丢弃缓存的历史，再次进入会重新拉取", async () => {
    const client = new QueryClient();
    const queryFn = vi.fn(async () => []);
    const observer = new QueryObserver(client, { ...historyQuery("t1"), queryFn });
    const unsubscribe = observer.subscribe(() => undefined);
    await vi.waitFor(() => expect(queryFn).toHaveBeenCalledTimes(1));
    // 先等数据真的进了缓存，下面"被丢弃"的断言才有意义（积压小问题 I18：原来第一次检查就成立）
    await vi.waitFor(() => expect(client.getQueryData(["history", "t1"])).toEqual([]));

    unsubscribe();

    await vi.waitFor(() => expect(client.getQueryData(["history", "t1"])).toBeUndefined());
  });
});

describe("retryWhileFailing", () => {
  it("加载失败时每 5 秒重试，成功后停止", () => {
    expect(retryWhileFailing({ state: { status: "error" } } as never)).toBe(5000);
    expect(retryWhileFailing({ state: { status: "success" } } as never)).toBe(false);
  });

  it("任何错误都照常重试（本机防护与访问令牌已去掉，D23）", () => {
    const state = { status: "error", error: new ApiError(401, "需要访问令牌") };
    expect(retryWhileFailing({ state } as never)).toBe(5000);
  });
});

describe("threadsQuery", () => {
  // 测试环境没有 window，TanStack Query 视为服务器端、不启动定时重刷，所以这里核对配置；
  // 重试规则本身由上面的 retryWhileFailing 测试覆盖，实际效果在浏览器验证
  it("有会话在跑或在等审批时每 5 秒刷新（状态点跟着变），加载失败时照常每 5 秒重试", () => {
    const query = (status: string, data?: unknown) => ({ state: { status, data } }) as never;
    expect(threadsQuery.refetchInterval(query("success", [{ activity: "running" }]))).toBe(5000);
    expect(threadsQuery.refetchInterval(query("success", [{ activity: "waiting" }]))).toBe(5000);
    expect(
      threadsQuery.refetchInterval(query("success", [{ activity: "failed" }, { activity: null }])),
    ).toBe(false);
    expect(threadsQuery.refetchInterval(query("error"))).toBe(5000);
  });

  it("会话列表与模型列表一样，加载失败时按同一规则自动重试", () => {
    expect(modelsQuery.refetchInterval).toBe(retryWhileFailing);
    // 不叠加 TanStack Query 默认的 3 次退避重试：失败立即显示（"正在重试"），之后每 5 秒一次
    expect(threadsQuery.retry).toBe(0);
    expect(modelsQuery.retry).toBe(0);
  });
});

describe("知识库查询", () => {
  it("检索失败立即显示原因，不叠加默认的 3 次重试（向量模型停掉时要等半分钟）", () => {
    expect(knowledgeQuery("q=x").retry).toBe(0);
  });

  it("增删改之后丢弃不在显示中的旧检索结果，再搜同一个词不会先闪出已删除的条目", async () => {
    const client = new QueryClient();
    client.setQueryData(["knowledge", "items", "q=旧词"], [{ id: "已删除" }]);
    await refreshKnowledge(client);
    expect(client.getQueryData(["knowledge", "items", "q=旧词"])).toBeUndefined();
  });
});
