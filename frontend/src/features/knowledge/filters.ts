import type { KnowledgeItem, PinnedSummary } from "../../api/types";

/**
 * 知识库页的视图：记忆 / 常驻（个人画像）/ 可疑 / 文档。没有"全部"：文档片段动辄成百上千，
 * 会把记忆淹没。文档视图不搜索时显示文档列表，搜索时显示命中的片段。可疑：像是写给智能体的
 * 指令、还没确认无害的记忆（设计 2026-10-23 6.6），它们不会带进对话，要在这里找得到。
 */
export type KnowledgeView = "memory" | "pinned" | "suspicious" | "documents";

const VIEW_NAMES: Record<KnowledgeView, string> = {
  memory: "记忆",
  pinned: "常驻",
  suspicious: "可疑",
  documents: "文档",
};

/** 页签上的字：可疑的有几条就写上（数的是一页，满一页写"100+"）。 */
export function viewLabel(view: KnowledgeView, flagged: number): string {
  if (view !== "suspicious" || flagged === 0) return VIEW_NAMES[view];
  return `${VIEW_NAMES[view]}（${flagged >= SUSPICIOUS_PAGE ? `${SUSPICIOUS_PAGE}+` : flagged}）`;
}

/** 数可疑的条目时取多少条。 */
export const SUSPICIOUS_PAGE = 100;

export interface KnowledgeFilter {
  view: KnowledgeView;
  tag: string | null; // 点了某个标签：只看带这个标签的
  query: string; // 搜索词：非空时按相关程度检索
  limit: number; // 显示多少条（"加载更多"每次加 PAGE_SIZE）
}

export const PAGE_SIZE = 50;

export const defaultFilter: KnowledgeFilter = {
  view: "memory",
  tag: null,
  query: "",
  limit: PAGE_SIZE,
};

/** 筛选条件 → 列表接口的查询参数。 */
export function knowledgeSearchParams(filter: KnowledgeFilter): string {
  const params = new URLSearchParams();
  if (filter.view === "memory") params.set("kind", "memory");
  if (filter.view === "pinned") params.set("pinned", "true");
  if (filter.view === "suspicious") {
    params.set("kind", "memory");
    params.set("suspicious", "true");
  }
  if (filter.view === "documents") params.set("kind", "document_chunk");
  if (filter.tag) params.set("tags", filter.tag);
  if (filter.query.trim()) params.set("q", filter.query.trim());
  params.set("limit", String(filter.limit));
  return params.toString();
}

/** 是否在筛选或检索（决定没有结果时说"没有符合条件的条目"还是"还没有记住任何信息"）。 */
export function isFiltered(filter: KnowledgeFilter): boolean {
  return filter.tag !== null || filter.query.trim() !== "";
}

export type ListView =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "empty"; text: string }
  | { kind: "items"; items: KnowledgeItem[] };

/**
 * 条目列表显示什么。出错时只显示原因：查询失败后仍保留着上一次的结果，
 * 一起显示会让人以为那就是这次的结果（里面可能还有已删除的条目）。
 */
export function listView(
  result: { isPending: boolean; isError: boolean; data: KnowledgeItem[] | undefined },
  filter: KnowledgeFilter,
): ListView {
  if (result.isError) return { kind: "error" };
  if (result.isPending || result.data === undefined) return { kind: "loading" };
  if (result.data.length === 0) {
    if (isFiltered(filter)) return { kind: "empty", text: "没有符合条件的条目" };
    const text = filter.view === "suspicious" ? "没有可疑的记忆" : "还没有记住任何信息";
    return { kind: "empty", text };
  }
  return { kind: "items", items: result.data };
}

/** 输入框里的标签：中英文逗号、顿号分隔，去空白、去重。 */
export function parseTags(text: string): string[] {
  const tags = text
    .split(/[,，、]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
  return [...new Set(tags)];
}

/**
 * 常驻信息超过上限时的提示（每次对话都会带上，太多既费钱也干扰回答）。上限是硬限制
 * （设计 2026-10-23 6.6），超过只会出现在调低上限以后：新设的常驻会被拒绝。
 */
export function pinnedNotice(
  summary: Pick<PinnedSummary, "total_tokens" | "token_limit">,
): string | null {
  if (summary.total_tokens <= summary.token_limit) return null;
  return `常驻信息约 ${summary.total_tokens} token，超过上限 ${summary.token_limit}：新设的常驻会被拒绝，先精简或取消部分常驻`;
}

const SOURCE_LABELS: Record<KnowledgeItem["source"], string> = {
  conversation: "对话中记下",
  manual: "手动添加",
  document: "来自文档",
};

export function sourceLabel(source: KnowledgeItem["source"]): string {
  return SOURCE_LABELS[source];
}

/** 接口一次最多返回的条数。 */
export const MAX_LIMIT = 200;

/**
 * 列表下方显示什么：返回条数达到当前上限时可以"加载更多"；
 * 已到接口上限时提示改用搜索或标签（再加载会被接口拒绝）。
 */
export function loadMore(count: number, limit: number): "none" | "more" | "capped" {
  if (count < limit) return "none";
  return limit >= MAX_LIMIT ? "capped" : "more";
}
