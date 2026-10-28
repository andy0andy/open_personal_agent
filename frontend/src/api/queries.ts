import { QueryClient, type Query } from "@tanstack/react-query";
import { api } from "./client";
import { pollWhileProcessing } from "../features/knowledge/documents";
import { pollWhileConnecting } from "../features/mcp/mcp";
import { hasActiveThread } from "../features/threads/activity";
import type { KnowledgeDocument, McpServersView, Thread, WorkspaceFile } from "./types";

/**
 * 会话的界面历史查询。
 * 离开会话（组件卸载）后立即丢弃缓存：会话进行中界面状态是实时更新的、不回写缓存，
 * 若保留旧缓存，切回来时会用切走之前的历史重建界面，刚才的对话就"消失"了。
 */
export function historyQuery(threadId: string) {
  return {
    queryKey: ["history", threadId],
    queryFn: () => api.history(threadId),
    staleTime: Infinity,
    gcTime: 0,
  };
}

/**
 * 失败后每 5 秒重试一次，直到成功（例如后端重启期间列表加载失败）。
 */
export function retryWhileFailing(query: Pick<Query, "state">): number | false {
  return query.state.status === "error" ? 5000 : false;
}

// retry: 0 —— 不叠加默认的 3 次退避重试，失败立即显示，之后由 retryWhileFailing 每 5 秒重试
export const threadsQuery = {
  queryKey: ["threads"],
  queryFn: api.listThreads,
  retry: 0,
  // 有会话在跑或在等审批时每 5 秒刷新一次，状态点跟着变（设计 2026-10-22 3.1）
  refetchInterval: (query: Pick<Query<Thread[]>, "state">): number | false =>
    retryWhileFailing(query) || (hasActiveThread(query.state.data) ? 5000 : false),
};

/** 归档的会话（会话列表底部"已归档（N）"）；键在 ["threads"] 下，刷新会话列表时一起刷新。 */
export const archivedThreadsQuery = {
  queryKey: ["threads", "archived"],
  queryFn: api.listArchivedThreads,
};

/** 不在会话列表里的会话（如已归档的）按 ID 取。 */
export function threadQuery(threadId: string) {
  return { queryKey: ["thread", threadId], queryFn: () => api.getThread(threadId), retry: 0 };
}

/** 会话搜索的结果（停顿后才查，见 features/threads/search.ts）。 */
export function threadSearchQuery(query: string) {
  return {
    queryKey: ["threads", "search", query],
    queryFn: () => api.searchThreads(query),
    staleTime: 10_000,
  };
}

export const modelsQuery = {
  queryKey: ["models"],
  queryFn: api.listModels,
  retry: 0,
  refetchInterval: retryWhileFailing,
};

/** 会话里的文件（上传与产物）；收到 file.created 或上传完成时由对话区主动刷新。 */
export function filesQuery(threadId: string) {
  return { queryKey: ["files", threadId], queryFn: () => api.listFiles(threadId) };
}

// 预览按文件的更新时间缓存：同一文件被改写后（文件 ID 不变）重新读取
export function tablePreviewQuery(file: WorkspaceFile, sheet: string | null) {
  return {
    queryKey: ["file-table", file.id, file.updated_at, sheet],
    queryFn: () => api.tablePreview(file.thread_id, file.id, sheet),
    retry: 0,
  };
}

export function fileTextQuery(file: WorkspaceFile) {
  return {
    queryKey: ["file-text", file.id, file.updated_at],
    queryFn: () => api.fileText(file.thread_id, file.id),
    retry: 0,
  };
}

/**
 * 知识库条目（筛选与检索）。知识库的查询键都以 "knowledge" 开头，增删改后用 refreshKnowledge 刷新。
 * retry: 0 —— 检索要向量化，向量模型停掉时一次失败约 5 秒，叠加默认的 3 次重试要等半分钟才显示原因
 */
export function knowledgeQuery(params: string) {
  return {
    queryKey: ["knowledge", "items", params],
    queryFn: () => api.listKnowledge(params),
    retry: 0,
  };
}

/**
 * 知识库增删改之后：正在显示的重新加载；不在显示中的旧检索结果直接丢弃
 * （否则再搜同一个词时，会先显示缓存里已删除或已改掉的条目）。
 */
export async function refreshKnowledge(queryClient: QueryClient): Promise<void> {
  queryClient.removeQueries({ queryKey: ["knowledge"], type: "inactive" });
  await queryClient.invalidateQueries({ queryKey: ["knowledge"] });
}

/** 知识库文档；有文档在处理时定时刷新，看得到进度。 */
export const documentsQuery = {
  queryKey: ["knowledge", "documents"],
  queryFn: api.listDocuments,
  refetchInterval: (query: Query<KnowledgeDocument[]>) => pollWhileProcessing(query.state.data),
};

/** 一个条目及其前后文（出处面板）。 */
export function itemContextQuery(itemId: string) {
  return {
    queryKey: ["knowledge", "context", itemId],
    queryFn: () => api.itemContext(itemId, 1),
    retry: 0,
  };
}

/** 设置页：MCP 服务的连接状态（启动后在后台连接、断线后自己重连，刷新间隔见 pollWhileConnecting）。 */
export const mcpServersQuery = {
  queryKey: ["settings", "mcp-servers"],
  queryFn: api.mcpServers,
  refetchInterval: (query: Query<McpServersView>) => pollWhileConnecting(query.state.data),
};

/** 模型页：网关里的全部模型、默认模型、可选的来源。 */
export const modelsAdminQuery = { queryKey: ["settings", "models"], queryFn: api.modelsAdmin };

/** MCP 页：审批规则与全部工具的生效结果。 */
export const approvalSettingsQuery = {
  queryKey: ["settings", "approval-rules"],
  queryFn: api.approvalSettings,
};

/** 用量统计页：最近 days 天，按浏览器所在时区分天。 */
export function usageSummaryQuery(days: number) {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return {
    queryKey: ["usage-summary", days, tz],
    queryFn: () => api.usageSummary(days, tz),
  };
}

/** 设置页：智能体技能（每次现读技能目录）。 */
export const skillsQuery = { queryKey: ["settings", "skills"], queryFn: api.skills };

/** 技能页的查看抽屉：正文与文件列表。 */
export function skillDetailQuery(id: string) {
  return { queryKey: ["settings", "skills", id], queryFn: () => api.skillDetail(id) };
}

/** 常驻条目（个人画像）与总 token 占用。 */
export const pinnedKnowledgeQuery = {
  queryKey: ["knowledge", "pinned"],
  queryFn: api.pinnedKnowledge,
};

/** 会话累计用量；每次运行结束后由对话区主动刷新。 */
export function threadUsageQuery(threadId: string) {
  return { queryKey: ["thread-usage", threadId], queryFn: () => api.threadUsage(threadId) };
}

/** 应用的查询客户端。 */
export function createQueryClient(): QueryClient {
  return new QueryClient();
}

/** 设置页（D22）：设置与 .workdata 里的文件。 */
export const appSettingsQuery = { queryKey: ["settings", "app"], queryFn: api.appSettings };
export const dataFilesQuery = { queryKey: ["settings", "files"], queryFn: api.dataFiles };
