import { describe, expect, it } from "vitest";
import type { KnowledgeItem } from "../../api/types";
import {
  defaultFilter,
  knowledgeSearchParams,
  loadMore,
  listView,
  parseTags,
  pinnedNotice,
  sourceLabel,
  viewLabel,
} from "./filters";

describe("knowledgeSearchParams", () => {
  it("按视图、标签、搜索词与条数生成查询参数", () => {
    const base = { tag: null, query: "", limit: 50 };
    expect(knowledgeSearchParams({ ...base, view: "memory" })).toBe("kind=memory&limit=50");
    expect(knowledgeSearchParams({ ...base, view: "pinned" })).toBe("pinned=true&limit=50");
    expect(knowledgeSearchParams({ view: "documents", tag: null, query: "报销", limit: 50 })).toBe(
      "kind=document_chunk&q=%E6%8A%A5%E9%94%80&limit=50",
    );
    expect(
      new URLSearchParams(
        knowledgeSearchParams({ ...base, view: "memory", tag: "工作", query: " 咖啡 " }),
      ),
    ).toEqual(new URLSearchParams({ kind: "memory", tags: "工作", q: "咖啡", limit: "50" }));
  });

  it("默认看记忆，每次显示 50 条", () => {
    expect(defaultFilter).toEqual({ view: "memory", tag: null, query: "", limit: 50 });
  });
});

describe("parseTags", () => {
  it("中英文逗号、顿号都能分隔，去空白、去重", () => {
    expect(parseTags("工作, 健康，饮食、 工作 ,,")).toEqual(["工作", "健康", "饮食"]);
    expect(parseTags("  ")).toEqual([]);
  });
});

describe("pinnedNotice", () => {
  it("常驻信息超过上限时提示精简（上限是硬限制，设计 2026-10-23 6.6）", () => {
    expect(pinnedNotice({ total_tokens: 1999, token_limit: 2000 })).toBeNull();
    expect(pinnedNotice({ total_tokens: 2300, token_limit: 2000 })).toBe(
      "常驻信息约 2300 token，超过上限 2000：新设的常驻会被拒绝，先精简或取消部分常驻",
    );
  });
});

describe("sourceLabel", () => {
  it("说明条目从哪里来", () => {
    expect(sourceLabel("conversation")).toBe("对话中记下");
    expect(sourceLabel("manual")).toBe("手动添加");
    expect(sourceLabel("document")).toBe("来自文档");
  });
});

describe("listView", () => {
  const item = { id: "k1", content: "用户养了一只狗" } as KnowledgeItem;
  const searching = { ...defaultFilter, query: "狗" };

  it("检索失败时只显示原因，不显示上一次缓存的结果", () => {
    expect(listView({ isPending: false, isError: true, data: [item] }, searching)).toEqual({
      kind: "error",
    });
  });

  it("加载中、没有结果、有结果", () => {
    expect(listView({ isPending: true, isError: false, data: undefined }, defaultFilter)).toEqual({
      kind: "loading",
    });
    expect(listView({ isPending: false, isError: false, data: [] }, defaultFilter)).toEqual({
      kind: "empty",
      text: "还没有记住任何信息",
    });
    expect(listView({ isPending: false, isError: false, data: [] }, searching)).toEqual({
      kind: "empty",
      text: "没有符合条件的条目",
    });
    expect(listView({ isPending: false, isError: false, data: [item] }, searching)).toEqual({
      kind: "items",
      items: [item],
    });
  });
});

describe("loadMore", () => {
  it("返回条数达到当前上限时可以加载更多；到了接口的上限 200 条就提示改用搜索", () => {
    expect(loadMore(30, 50)).toBe("none");
    expect(loadMore(50, 50)).toBe("more");
    expect(loadMore(150, 150)).toBe("more");
    expect(loadMore(200, 200)).toBe("capped");
  });
});

describe("可疑视图（审查 I1：被标为可疑的记忆要找得到）", () => {
  it("只看可疑的记忆", () => {
    const base = { tag: null, query: "", limit: 50 };
    expect(knowledgeSearchParams({ ...base, view: "suspicious" })).toBe(
      "kind=memory&suspicious=true&limit=50",
    );
  });

  it("有可疑的时页签带上数量，满一页写“100+”", () => {
    expect(viewLabel("suspicious", 0)).toBe("可疑");
    expect(viewLabel("suspicious", 3)).toBe("可疑（3）");
    expect(viewLabel("suspicious", 100)).toBe("可疑（100+）");
    expect(viewLabel("memory", 3)).toBe("记忆");
  });

  it("没有可疑的记忆时这样说", () => {
    const filter = { ...defaultFilter, view: "suspicious" as const };
    expect(listView({ isPending: false, isError: false, data: [] }, filter)).toEqual({
      kind: "empty",
      text: "没有可疑的记忆",
    });
  });
});
