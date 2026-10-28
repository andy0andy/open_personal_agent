import type {
  ApprovalAnswer,
  ApprovalSettingsView,
  ItemContext,
  KnowledgeCreate,
  KnowledgeDocument,
  KnowledgeItem,
  KnowledgeUpdate,
  McpProbeResult,
  McpServerInput,
  McpServersView,
  ModelInfo,
  ModelInput,
  ModelTestResult,
  ModelView,
  ModelsView,
  PinnedSummary,
  ReloadResult,
  RunHistory,
  RunRecord,
  SkillDetail,
  SkillInfo,
  TablePreview,
  Thread,
  ThreadCreate,
  ThreadCreated,
  ThreadSearchResult,
  SettingView,
  DataFileView,
  ThreadUpdate,
  ThreadUsage,
  UsageSummaryView,
  WorkspaceFile,
} from "./types";
import { ensureToken, refreshToken } from "./session";

const TOKEN_HEADER = "X-Session-Token";

/** 把后端的错误响应转成看得懂的一句话：FastAPI 的 422 校验错误的 detail 是数组。 */
export function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const reasons = detail
      .map((item) => (item as { msg?: unknown }).msg)
      .filter((msg): msg is string => typeof msg === "string");
    if (reasons.length > 0) return `请求参数有误：${reasons.join("；")}`;
  }
  return `请求失败：${status}`;
}

/** 后端返回的错误：带上状态码，便于按状态区分处理（如 409：会话已有进行中的运行）。 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** 显示错误时只取错误信息本身（String(error) 会带上 "Error:" / "TypeError:" 前缀）。 */
export function readableError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * 发请求；连不上或状态码不是 2xx 时抛出看得懂的错误。
 * 每个请求都带本机令牌（D25）；401 时重取一次令牌再发（后端重启后令牌会变）。
 */
async function send(path: string, init?: RequestInit, retried = false): Promise<Response> {
  const token = await ensureToken();
  let resp: Response;
  try {
    resp = await fetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers, [TOKEN_HEADER]: token },
    });
  } catch (error) {
    if (init?.signal?.aborted) throw error; // 自己取消的（如移除还在传的附件）：不是连不上
    // 浏览器只给出 "Failed to fetch" 之类的原始报错，换成看得懂的说明
    throw new Error("无法连接到后端，请确认服务已启动", { cause: error });
  }
  if (resp.status === 401 && !retried) {
    await refreshToken();
    return send(path, init, true);
  }
  if (!resp.ok) {
    const body: unknown = await resp.json().catch(() => null);
    throw new ApiError(resp.status, errorMessage(resp.status, body));
  }
  return resp;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await send(path, init);
  if (resp.status === 204) return undefined as T; // 没有内容（如保存顺序）
  return (await resp.json()) as T;
}

/** 导出这个会话为 Markdown 的下载地址（设计 2026-10-23 6.2；GET 带 Cookie 即可）。 */
export function exportUrl(threadId: string, tz: string): string {
  // 每轮的时间按浏览器所在时区写（8000 实测：原来按 UTC）
  return `/api/threads/${threadId}/export?tz=${encodeURIComponent(tz)}`;
}

/** 会话里一个文件的地址：默认在页面里打开，download 为真时作为附件下载。 */
export function fileContentUrl(threadId: string, fileId: string, download: boolean): string {
  const url = `/api/threads/${threadId}/files/${fileId}/content`;
  return download ? `${url}?download=1` : url;
}

export const api = {
  listThreads: () => request<Thread[]>("/threads"),
  /** 会话搜索（设计 2026-10-23 6.1）：标题匹配（含已归档的）与内容里提到。 */
  searchThreads: (query: string) =>
    request<ThreadSearchResult>(`/threads/search?q=${encodeURIComponent(query)}`),
  /** 新建会话；带上第一条消息时一次完成：设好模型与权限、发起运行（设计 2026-10-23 6.4）。 */
  createThread: (input: Partial<ThreadCreate> = {}) =>
    request<ThreadCreated>("/threads", { method: "POST", body: JSON.stringify(input) }),
  /** 归档的会话（设计 2026-10-23 6.5）。 */
  listArchivedThreads: () => request<Thread[]>("/threads?archived=true"),
  /** 看过了这个会话：清掉"有新回答"（设计 2026-10-23 6.5）。 */
  markViewed: (threadId: string) =>
    request<undefined>(`/threads/${threadId}/viewed`, { method: "POST" }),
  /** 按 ID 取会话（不在列表里的也行，如已归档的，设计 2026-10-23 6.1）。 */
  getThread: (threadId: string) => request<Thread>(`/threads/${threadId}`),
  history: (threadId: string) => request<RunHistory[]>(`/threads/${threadId}/history`),
  listModels: () => request<ModelInfo[]>("/models"),
  /** attachments：随消息发出的文件（已上传到本会话的文件 ID）。 */
  // 模型与审批权限取会话上的（PATCH /threads/{id} 改），不随消息发
  startRun: (threadId: string, message: string, attachments: string[] = []) =>
    request<RunRecord>(`/threads/${threadId}/runs`, {
      method: "POST",
      body: JSON.stringify(attachments.length > 0 ? { message, attachments } : { message }),
    }),
  /**
   * 上传文件到会话的 uploads/：请求体就是文件本身，文件名编码后放在 X-File-Name 请求头
   * （自定义请求头也让跨站网页无法直接伪造上传，设计文档 12.2）。
   */
  uploadFile: (threadId: string, file: File, signal?: AbortSignal) =>
    request<WorkspaceFile>(`/threads/${threadId}/files`, {
      method: "POST",
      body: file,
      signal,
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        "X-File-Name": encodeURIComponent(file.name),
      },
    }),
  /** 设置页（D22）：设置存数据库，同名环境变量优先。 */
  appSettings: () => request<SettingView[]>("/settings/app"),
  updateAppSetting: (key: string, value: unknown) =>
    request<SettingView>(`/settings/app/${encodeURIComponent(key)}`, {
      method: "PUT",
      body: JSON.stringify({ value }),
    }),
  resetAppSetting: (key: string) =>
    request<SettingView>(`/settings/app/${encodeURIComponent(key)}`, { method: "DELETE" }),
  dataFiles: () => request<DataFileView[]>("/settings/files"),
  /** 改会话的标题、模型或审批权限：只提交要改的几项。 */
  updateThread: (threadId: string, patch: ThreadUpdate) =>
    request<Thread>(`/threads/${threadId}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteThread: (threadId: string) =>
    request<undefined>(`/threads/${threadId}`, { method: "DELETE" }),
  reorderThreads: (threadIds: string[]) =>
    request<undefined>("/threads/order", {
      method: "PUT",
      body: JSON.stringify({ thread_ids: threadIds }),
    }),
  cancelRun: (runId: string) =>
    request<RunRecord>(`/runs/${runId}/cancel`, { method: "POST", body: "{}" }),
  /** "重试这一轮"（D26）：从这次运行之前的存档分叉重跑，返回新运行；不能重试时 409。 */
  retryRun: (runId: string) =>
    request<RunRecord>(`/runs/${runId}/retry`, { method: "POST", body: "{}" }),
  /** 最近 days 天的用量汇总；按天分组用 tz 时区（浏览器所在时区）。 */
  usageSummary: (days: number, tz: string) =>
    request<UsageSummaryView>(`/usage/summary?days=${days}&tz=${encodeURIComponent(tz)}`),
  /** 模型页（D22）：模型全部在网关数据库里，都能改能删。 */
  modelsAdmin: () => request<ModelsView>("/settings/models"),
  addModel: (model: ModelInput) =>
    request<ModelView>("/settings/models", { method: "POST", body: JSON.stringify(model) }),
  updateModel: (model: ModelInput) =>
    request<ModelView>(`/settings/models/${encodeURIComponent(model.name)}`, {
      method: "PUT",
      body: JSON.stringify(model),
    }),
  /** 删除页面加的模型；返回改用默认模型的会话数。 */
  deleteModel: (name: string) =>
    request<{ reassigned: number }>(`/settings/models/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
  /** 真的调用一次（花几个 token）。 */
  testModel: (name: string) =>
    request<ModelTestResult>(`/settings/models/${encodeURIComponent(name)}/test`, {
      method: "POST",
      body: "{}",
    }),
  setDefaultChatModel: (name: string) =>
    request<ModelsView>("/settings/models/default", {
      method: "PUT",
      body: JSON.stringify({ name }),
    }),
  mcpServers: () => request<McpServersView>("/settings/mcp-servers"),
  /** 加入一个或多个 MCP 服务（写进 .workdata/config/，D21）：全部成功或全部不加。 */
  addMcpServers: (servers: McpServerInput[]) =>
    request<McpServersView>("/settings/mcp-servers", {
      method: "POST",
      body: JSON.stringify({ servers }),
    }),
  updateMcpServer: (server: McpServerInput) =>
    request<McpServersView>(`/settings/mcp-servers/${server.name}`, {
      method: "PUT",
      body: JSON.stringify(server),
    }),
  setMcpServerEnabled: (name: string, enabled: boolean) =>
    request<McpServersView>(`/settings/mcp-servers/${name}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }),
  deleteMcpServer: (name: string) =>
    request<undefined>(`/settings/mcp-servers/${name}`, { method: "DELETE" }),
  /** 测试连接，不保存。 */
  testMcpServer: (server: McpServerInput) =>
    request<McpProbeResult>("/settings/mcp-servers/test", {
      method: "POST",
      body: JSON.stringify(server),
    }),
  setToolAction: (tool: string, action: "auto" | "ask") =>
    request<ApprovalSettingsView>(`/settings/approval-rules/tools/${encodeURIComponent(tool)}`, {
      method: "PUT",
      body: JSON.stringify({ action }),
    }),
  approvalSettings: () => request<ApprovalSettingsView>("/settings/approval-rules"),
  skills: () => request<SkillInfo[]>("/settings/skills"),
  skillDetail: (id: string) => request<SkillDetail>(`/settings/skills/${encodeURIComponent(id)}`),
  /** 上传技能：files 的 content 是 base64，path 带文件夹层级（D21：检查完才写进 .workdata/skills/）。 */
  uploadSkill: (files: { path: string; content: string }[]) =>
    request<SkillInfo>("/settings/skills", { method: "POST", body: JSON.stringify({ files }) }),
  setSkillEnabled: (id: string, enabled: boolean) =>
    request<SkillInfo>(`/settings/skills/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }),
  deleteSkill: (id: string) =>
    request<undefined>(`/settings/skills/${encodeURIComponent(id)}`, { method: "DELETE" }),
  /** 重读 MCP 服务清单与审批规则、重连 MCP 服务、刷新模型信息。 */
  reloadSettings: () => request<ReloadResult>("/settings/reload", { method: "POST", body: "{}" }),
  /** 提交审批决定，运行接着跑（结果随推送到达）。 */
  /** 运行中插话（设计 2026-10-23 6.3）：主智能体下一步开始前送达；等审批、已结束时 409。 */
  interject: (runId: string, message: string) =>
    request<undefined>(`/runs/${runId}/interject`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  resumeRun: (runId: string, answers: ApprovalAnswer[]) =>
    request<RunRecord>(`/runs/${runId}/resume`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),
  threadUsage: (threadId: string) => request<ThreadUsage>(`/threads/${threadId}/usage`),
  listFiles: (threadId: string) => request<WorkspaceFile[]>(`/threads/${threadId}/files`),
  /** CSV / Excel 的前若干行；sheet 为 Excel 的工作表名，null 表示第一个。 */
  tablePreview: (threadId: string, fileId: string, sheet: string | null) =>
    request<TablePreview>(
      `/threads/${threadId}/files/${fileId}/table` +
        (sheet === null ? "" : `?sheet=${encodeURIComponent(sheet)}`),
    ),
  /** 文件原文（Markdown、代码等文字文件的预览）。 */
  fileText: async (threadId: string, fileId: string) =>
    (await send(`/threads/${threadId}/files/${fileId}/content`)).text(),
  /** 知识库条目；params 为筛选与检索的查询参数（见 knowledge/filters.ts）。 */
  listKnowledge: (params: string) =>
    request<KnowledgeItem[]>(`/knowledge/items${params ? `?${params}` : ""}`),
  addKnowledge: (body: KnowledgeCreate) =>
    request<KnowledgeItem>("/knowledge/items", { method: "POST", body: JSON.stringify(body) }),
  updateKnowledge: (itemId: string, body: KnowledgeUpdate) =>
    request<KnowledgeItem>(`/knowledge/items/${itemId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteKnowledge: (itemId: string) =>
    request<undefined>(`/knowledge/items/${itemId}`, { method: "DELETE" }),
  pinnedKnowledge: () => request<PinnedSummary>("/knowledge/pinned"),
  /** 上传文档到知识库：请求体就是文件本身，文件名编码后放在 X-File-Name 请求头。 */
  uploadDocument: (file: File) =>
    request<KnowledgeDocument>("/knowledge/documents", {
      method: "POST",
      body: file,
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        "X-File-Name": encodeURIComponent(file.name),
      },
    }),
  listDocuments: () => request<KnowledgeDocument[]>("/knowledge/documents"),
  deleteDocument: (documentId: string) =>
    request<undefined>(`/knowledge/documents/${documentId}`, { method: "DELETE" }),
  reprocessDocument: (documentId: string) =>
    request<KnowledgeDocument>(`/knowledge/documents/${documentId}/reprocess`, {
      method: "POST",
      body: "{}",
    }),
  /** 一个条目及其前后各 window 段（回答里的出处点开时显示）。 */
  itemContext: (itemId: string, window = 1) =>
    request<ItemContext>(`/knowledge/items/${itemId}/context?window=${window}`),
  /** 把会话里的文件加入知识库（后台处理）。 */
  addFileToKnowledge: (threadId: string, fileId: string) =>
    request<KnowledgeDocument>(`/threads/${threadId}/files/${fileId}/knowledge`, {
      method: "POST",
      body: "{}",
    }),
};
