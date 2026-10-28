// 与 backend 接口对应的类型：由 make types 从接口文档与事件定义自动生成（generated/，不要手改），
// 这里只起简短的别名，并补上接口文档表达不了的部分（信封里按事件类型区分的 data）
import type { components } from "./generated/schema";

type Schemas = components["schemas"];

export type Thread = Schemas["Thread"];
export type ThreadUpdate = Schemas["ThreadUpdate"];
/** 会话的审批权限（D23）：每次先问 / 只问执行命令 / 跳过所有审批。 */
export type PermissionMode = Thread["permission_mode"];
export type ModelInfo = Schemas["ModelInfo"];
export type ModelView = Schemas["ModelView"];
export type ModelsView = Schemas["ModelsView"];
export type ModelInput = Schemas["ModelInput"];
export type ModelSource = Schemas["ModelSource"];
export type ModelTestResult = Schemas["ModelTestResult"];
export type RunStatus = Schemas["RunStatus"];
export type RunRecord = Schemas["RunRecord"];
export type RunAttachment = Schemas["RunAttachment"];
export type UsageTotals = Schemas["UsageTotals"];
export type InterruptedUsage = Schemas["InterruptedUsage"];
/** 运行失败的类型（设计 2026-10-23 4.5）：报错卡片按它给按钮。 */
export type ErrorKind = Schemas["ErrorKind"];
export type ModelUsage = Schemas["ModelUsage"];
export type ThreadUsage = Schemas["ThreadUsage"];
export type TodoItem = Schemas["TodoItem"];
export type WorkspaceFile = Schemas["WorkspaceFile"];
export type TablePreview = Schemas["TablePreview"];
export type KnowledgeItem = Schemas["KnowledgeItem"];
export type KnowledgeCreate = Schemas["KnowledgeCreate"];
export type KnowledgeUpdate = Schemas["KnowledgeUpdate"];
export type PinnedSummary = Schemas["PinnedSummary"];
export type KnowledgeDocument = Schemas["KnowledgeDocument"];
export type ItemContext = Schemas["ItemContext"];
export type ApprovalRequest = Schemas["ApprovalRequest"];
export type ApprovalAction = Schemas["ApprovalAction"];
export type ApprovalAnswer = Schemas["ApprovalAnswer"];
export type ToolDecision = Schemas["ToolDecision"];
export type McpServersView = Schemas["McpServersView"];
export type McpServerView = Schemas["McpServerView"];
export type McpServerInput = Schemas["McpServerInput"];
export type McpProbeResult = Schemas["McpProbeResult"];
export type ApprovalSettingsView = Schemas["ApprovalSettingsView"];
export type ToolApproval = Schemas["ToolApproval"];
export type SkillInfo = Schemas["SkillInfo"];
export type SkillDetail = Schemas["SkillDetail"];
export type ReloadResult = Schemas["ReloadResult"];
export type UsageSummaryView = Schemas["UsageSummaryView"];
export type DayUsage = Schemas["DayUsage"];
export type UsageBucket = Schemas["UsageBucket"];

/** 智能体事件（agents 的事件协议）。 */
export type AgentEvent = Schemas["AgentEvent"];
type EventType = AgentEvent["type"];
type EventData<T extends EventType> = Omit<Extract<AgentEvent, { type: T }>, "type" | "agent_path">;

/** 一次模型调用的用量（推送事件 usage 的内容）。 */
export type UsageData = EventData<"usage">;
/** 主智能体一次调用时上下文各部分的大小（推送事件 context.usage，设计 2026-10-23 4.7）。 */
export type ContextUsageData = EventData<"context.usage">;

// 界面历史里合并过的逐字片段带 full_text: true，表示 text 是这段内容到此为止的全文，应整体替换
type DeltaExtra<T extends EventType> = T extends "message.delta" | "thinking.delta"
  ? { full_text?: boolean }
  : unknown;

/** 推送与界面历史里的事件：信封字段 + 按 type 区分的 data（backend 把事件除 type、agent_path 外的字段放进 data）。 */
export type EventEnvelope = {
  [T in EventType]: Omit<Schemas["EventEnvelope"], "type" | "data"> & {
    type: T;
    data: EventData<T> & DeltaExtra<T>;
  };
}[EventType];

export type RunHistory = Omit<Schemas["RunHistory"], "events"> & { events: EventEnvelope[] };
/** 设置页的一项设置与 .workdata 里的文件（D22）。 */
export type SettingView = Schemas["SettingView"];
export type DataFileView = Schemas["DataFileView"];
export type ThreadSearchResult = Schemas["ThreadSearchResult"];
export type ConversationHitView = Schemas["ConversationHitView"];
export type ThreadCreate = Schemas["ThreadCreate"];
export type ThreadCreated = Schemas["ThreadCreated"];
