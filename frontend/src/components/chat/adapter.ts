import type { ThreadMessageLike } from "@assistant-ui/react";
import type { ErrorKind, UsageData } from "../../api/types";
import { STOPPED_DECISION, decisionView, type DecisionView } from "../../features/chat/approvals";
import type { ChatItem, ChatState } from "../../features/chat/reducer";
import { fileName } from "../format";

type AssistantPart = Exclude<ThreadMessageLike["content"], string>[number];

/** 子智能体卡片的工具名；卡片的内部步骤放在 artifact 里。 */
export const SUBAGENT_TOOL = "subagent";

export interface SubagentArtifact {
  name: string;
  description: string;
  items: ChatItem[];
  paused?: boolean; // 同一轮里有别的调用在等你审批：它跟着停着，不是被打断
}

/**
 * 工具调用、子智能体这类步骤的显示状态。waiting：在等你审批；paused：同一轮里别的调用在等你审批，
 * 它跟着停着（不是被打断，也不需要你审批）。
 */
export type StepState = "running" | "waiting" | "paused" | "success" | "error" | "interrupted";

/**
 * 步骤片段的显示状态。没有结果时，assistant-ui 给的片段状态就是所在消息的状态：
 * 消息还在运行才算"运行中"，否则是被停止或运行失败打断的（不能一直转圈）。
 */
export function stepState(
  result: unknown,
  isError: boolean | undefined,
  partStatus: { type: string },
  waiting = false,
  paused = false,
): StepState {
  if (result !== undefined) return isError ? "error" : "success";
  if (waiting) return "waiting"; // 等你审批：运行停着，但不是被打断
  if (paused) return "paused";
  return partStatus.type === "running" ? "running" : "interrupted";
}

/**
 * 子智能体内部步骤的显示状态：子智能体已不在运行（active 为假）时，未结束的步骤是被打断的；
 * 跟着别的审批停着时（paused）是等待中。
 */
export function itemState(
  status: "running" | "waiting" | "success" | "error",
  active: boolean,
  paused = false,
): StepState {
  if (status !== "running") return status;
  if (paused) return "paused";
  return active ? "running" : "interrupted";
}

/**
 * 工具行的附加信息（artifact）：waiting 为真表示在等你审批；起止时间用来显示用时，
 * waited 为真表示等过审批（用时里有等你的时间，不显示）；decision 是处理完的审批（并入工具行）。
 * runningAt 是工具真正开始执行的时间（设计 2026-10-23 5.7）：有它时用时从它算起，等过审批的也显示。
 */
export interface ToolArtifact {
  waiting: boolean;
  paused?: boolean; // 同一轮里别的调用在等你审批，它跟着停着
  startedAt?: string;
  finishedAt?: string;
  waited?: boolean;
  runningAt?: string;
  decision?: DecisionView;
  exitCode?: number; // 执行命令的真实退出码（设计 2026-10-23 5.4）
  stderr?: string;
}

/**
 * 一轮里的审批怎么显示（设计 2026-10-22 3.6）：等你决定的，卡片代表它的工具（工具不再单独一行）；
 * 处理完的、等待中被停止的，决定并入对应的工具行，卡片不再显示。
 */
interface ApprovalLayout {
  /** 这一轮里有等你决定的审批：没结束的其他步骤跟着停着 */
  open: boolean;
  hidden: Set<string>;
  decisions: Map<string, DecisionView>;
  /** 处理完了，但有工具不在这一层（如在子智能体里）：仍显示它的结果 */
  keep: Set<string>;
}

function layoutApprovals(group: ChatItem[]): ApprovalLayout {
  const tools = new Set(
    group.flatMap((item) => (item.kind === "tool" ? [item.id.slice("tool-".length)] : [])),
  );
  const layout: ApprovalLayout = {
    open: false,
    hidden: new Set(),
    decisions: new Map(),
    keep: new Set(),
  };
  for (const item of group) {
    if (item.kind !== "approval") continue;
    const open = item.status === "pending" || item.status === "submitting";
    layout.open ||= open;
    for (const request of item.requests) {
      const answer = item.answers?.find((entry) => entry.interrupt_id === request.interrupt_id);
      request.actions.forEach((action, index) => {
        if (open) return layout.hidden.add(action.call_id);
        if (!tools.has(action.call_id)) return layout.keep.add(item.id);
        const decision = answer?.decisions?.[index];
        if (item.status === "stopped") layout.decisions.set(action.call_id, STOPPED_DECISION);
        else if (decision) layout.decisions.set(action.call_id, decisionView(action, decision));
      });
    }
  }
  return layout;
}

/** 用户消息下方的附件标签（点开在文件面板里预览）。 */
export interface UserAttachment {
  fileId: string;
  name: string;
  size: number;
}

/** 文件地址：由页面按所在会话提供（download 为真时作为附件下载）。 */
export type FileUrl = (fileId: string, download: boolean) => string;

/** 产物文件卡片的数据（数据片段 data-file）。 */
export interface FileCardData {
  fileId: string;
  name: string;
  path: string;
  size: number;
  mediaType: string;
  url: string;
  downloadUrl: string;
}

/**
 * 思考的数据（数据片段 data-thinking，设计 2026-10-22 3.4）：seconds 由起止时间算出，
 * 算不出（旧记录、被打断）时为空；running：这段思考还在进行。
 */
export interface ThinkingData {
  text: string;
  seconds: number | null;
  running: boolean;
}

/** "已记住"提示的数据（数据片段 data-memory）。 */
export interface MemoryNoteData {
  content: string;
  pinned: boolean;
  suspicious?: string; // 可疑原因：在知识库页确认前不会用上
}

/**
 * 运行中插的话（数据片段 data-interjection，设计 2026-10-23 6.3）：queued 为真表示排着、还没送达；
 * undelivered 为真表示这一轮结束时也没送达。
 */
export interface InterjectionData {
  text: string;
  queued: boolean;
  undelivered?: boolean;
}

/** 报错卡片要用的：哪次运行、什么类型、能否重试（设计 2026-10-23 4.5，D26）。 */
export interface ErrorInfo {
  runId: string;
  kind: ErrorKind;
  retryable: boolean;
}

/** 收起的失败轮（数据片段 data-retried）："第 N 次失败：原因（已重试）"。 */
export interface RetriedData {
  attempt: number;
  text: string;
}

/** 一轮回答的用量（含子智能体）：显示在回答下方，可展开每次调用明细。 */
export interface TurnUsage {
  input_tokens: number;
  output_tokens: number;
  calls: UsageData[];
}

/**
 * 把事件处理器的状态转换成 assistant-ui 的消息（设计文档 13.1 映射表）：
 * 两条用户消息之间的思考、回答、工具调用、子智能体合并为一条助手消息；
 * 运行失败映射为"未完成"并带错误原因，停止映射为"未完成（已取消）"。
 */
export function toThreadMessages(state: ChatState, fileUrl: FileUrl): ThreadMessageLike[] {
  const groups: ChatItem[][] = [];
  for (const item of state.items) {
    const last = groups.at(-1);
    if (item.kind !== "user" && last && last[0]?.kind !== "user") last.push(item);
    else groups.push([item]);
  }
  // 排队的插话显示在这一轮的末尾；这一轮还没有回答时单独成一条助手消息
  const queued = (state.queued ?? []).map((item): AssistantPart => ({
    type: "data-interjection",
    data: { text: item.text, queued: true } satisfies InterjectionData,
  }));
  if (queued.length > 0 && groups.at(-1)?.[0]?.kind === "user") groups.push([]);
  return groups.map((group, index) => {
    const first = group[0];
    if (first?.kind === "user") return userMessage(first);
    const last = index === groups.length - 1;
    const running = last && state.running;
    const approvals = layoutApprovals(group);
    const parts = group.flatMap((item) => toPart(item, fileUrl, approvals, running));
    if (last) parts.push(...queued);
    return {
      id: `a-${first?.id ?? index}`,
      role: "assistant",
      content: parts,
      status: turnStatus(group, running),
      ...turnMetadata(group),
    };
  });
}

function userMessage(item: Extract<ChatItem, { kind: "user" }>): ThreadMessageLike {
  const attachments: UserAttachment[] = (item.attachments ?? []).map((file) => ({
    fileId: file.id,
    name: fileName(file.path),
    size: file.size,
  }));
  return {
    id: item.id,
    role: "user",
    content: [{ type: "text", text: item.text }],
    ...(attachments.length > 0 ? { metadata: { custom: { attachments } } } : {}),
  };
}

/** 运行失败为"未完成"并带错误原因，停止为"未完成（已取消）"。 */
function turnStatus(group: ChatItem[], running: boolean): ThreadMessageLike["status"] {
  const errorItem = group.find((item) => item.kind === "error");
  if (errorItem?.kind === "error") {
    return { type: "incomplete", reason: "error", error: errorItem.text };
  }
  if (group.some((item) => item.kind === "stopped")) {
    return { type: "incomplete", reason: "cancelled" };
  }
  return running ? { type: "running" } : { type: "complete", reason: "stop" };
}

/** 回答下方要显示的：本轮用量、已停止、被中断调用的估算、耗时、报错卡片的信息。 */
function turnMetadata(group: ChatItem[]): Pick<ThreadMessageLike, "metadata"> {
  const errorItem = group.find((item) => item.kind === "error");
  const errorInfo: ErrorInfo | undefined =
    errorItem?.kind === "error"
      ? { runId: errorItem.runId, kind: errorItem.errorKind, retryable: errorItem.retryable }
      : undefined;
  const stopped = group.some((item) => item.kind === "stopped");
  const usage = turnUsage(group);
  const timing = turnTiming(group);
  const interruptedUsage = group.flatMap((item) =>
    (item.kind === "stopped" || item.kind === "error") && item.interruptedUsage
      ? [item.interruptedUsage]
      : [],
  )[0];
  if (!usage && !stopped && !interruptedUsage && !timing && !errorInfo) return {};
  return {
    metadata: {
      custom: {
        usage,
        stopped,
        ...(interruptedUsage ? { interruptedUsage } : {}),
        ...(timing ? { timing } : {}),
        ...(errorInfo ? { error: errorInfo } : {}),
      },
    },
  };
}

function turnTiming(
  group: ChatItem[],
): { startedAt: string; finishedAt?: string; pausedMs?: number } | undefined {
  const item = group.find((entry) => entry.kind === "timing");
  if (item?.kind !== "timing") return undefined;
  return {
    startedAt: item.startedAt,
    finishedAt: item.finishedAt,
    ...(item.pausedMs ? { pausedMs: item.pausedMs } : {}),
  };
}

function toPart(
  item: ChatItem,
  fileUrl: FileUrl,
  approvals: ApprovalLayout,
  running: boolean,
): AssistantPart[] {
  switch (item.kind) {
    case "assistant":
      return [{ type: "text", text: item.text }];
    case "thinking":
      return [thinkingPart(item, running)];
    case "tool":
      return toolPart(item, approvals);
    case "subagent":
      return [subagentPart(item, approvals.open)];
    case "todos":
      return [{ type: "data-todos", data: item.todos }];
    case "file":
      return [filePart(item, fileUrl)];
    case "memory": {
      const data: MemoryNoteData = {
        content: item.content,
        pinned: item.pinned,
        ...(item.suspicious ? { suspicious: item.suspicious } : {}),
      };
      return [{ type: "data-memory", data }];
    }
    case "interjection": {
      const data: InterjectionData = {
        text: item.text,
        queued: false,
        ...(item.undelivered ? { undelivered: true } : {}),
      };
      return [{ type: "data-interjection", data }];
    }
    case "retried": {
      const data: RetriedData = { attempt: item.attempt, text: item.text };
      return [{ type: "data-retried", data }];
    }
    case "approval":
      return item.status === "pending" ||
        item.status === "submitting" ||
        approvals.keep.has(item.id)
        ? [{ type: "data-approval", data: item }]
        : [];
    default:
      return []; // user / usage / stopped / error / timing 不是消息片段
  }
}

function thinkingPart(
  item: Extract<ChatItem, { kind: "thinking" }>,
  running: boolean,
): AssistantPart {
  const data: ThinkingData = {
    text: item.text,
    seconds:
      item.startedAt && item.endedAt
        ? Math.round((Date.parse(item.endedAt) - Date.parse(item.startedAt)) / 1000)
        : null,
    running: running && item.endedAt === undefined,
  };
  return { type: "data-thinking", data };
}

/** 工具行；等你决定的审批代表它的工具，这里不再单独一行。 */
function toolPart(
  item: Extract<ChatItem, { kind: "tool" }>,
  approvals: ApprovalLayout,
): AssistantPart[] {
  const callId = item.id.slice("tool-".length);
  if (approvals.hidden.has(callId)) return [];
  const decision = approvals.decisions.get(callId);
  const timing = {
    ...(item.startedAt ? { startedAt: item.startedAt } : {}),
    ...(item.finishedAt ? { finishedAt: item.finishedAt } : {}),
    ...(item.waited ? { waited: true } : {}),
    ...(item.runningAt ? { runningAt: item.runningAt } : {}),
    ...(decision ? { decision } : {}),
    ...(item.exitCode !== undefined ? { exitCode: item.exitCode } : {}),
    ...(item.stderr ? { stderr: item.stderr } : {}),
  };
  const waiting = item.status === "waiting";
  const paused = approvals.open && item.status === "running";
  return [
    {
      type: "tool-call",
      toolCallId: item.id,
      toolName: item.name,
      argsText: JSON.stringify(item.args, null, 2),
      ...(waiting || paused || Object.keys(timing).length > 0
        ? {
            artifact: {
              waiting,
              ...(paused ? { paused: true } : {}),
              ...timing,
            } satisfies ToolArtifact,
          }
        : {}),
      ...(item.status === "running" || item.status === "waiting"
        ? {}
        : { result: item.output, isError: item.status === "error" }),
    },
  ];
}

function subagentPart(
  item: Extract<ChatItem, { kind: "subagent" }>,
  approvalOpen: boolean,
): AssistantPart {
  const artifact: SubagentArtifact = {
    name: item.name,
    description: item.description,
    items: item.items,
    ...(approvalOpen && item.status === "running" ? { paused: true } : {}),
  };
  return {
    type: "tool-call",
    toolCallId: item.id,
    toolName: SUBAGENT_TOOL,
    argsText: item.description,
    artifact,
    ...(item.status === "running" ? {} : { result: item.output, isError: item.status === "error" }),
  };
}

function filePart(item: Extract<ChatItem, { kind: "file" }>, fileUrl: FileUrl): AssistantPart {
  const data: FileCardData = {
    fileId: item.fileId,
    name: fileName(item.path),
    path: item.path,
    size: item.size,
    mediaType: item.mediaType,
    url: fileUrl(item.fileId, false),
    downloadUrl: fileUrl(item.fileId, true),
  };
  return { type: "data-file", data };
}

/** 汇总一轮里所有模型调用的用量，包括子智能体内部的调用。 */
function turnUsage(group: ChatItem[]): TurnUsage | undefined {
  const calls = collectUsage(group);
  if (calls.length === 0) return undefined;
  return {
    input_tokens: calls.reduce((sum, call) => sum + call.input_tokens, 0),
    output_tokens: calls.reduce((sum, call) => sum + call.output_tokens, 0),
    calls,
  };
}

function collectUsage(items: ChatItem[]): UsageData[] {
  return items.flatMap((item) =>
    item.kind === "usage" ? [item.usage] : item.kind === "subagent" ? collectUsage(item.items) : [],
  );
}
