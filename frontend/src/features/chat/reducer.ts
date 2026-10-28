import type {
  ApprovalAnswer,
  ApprovalRequest,
  ContextUsageData,
  ErrorKind,
  EventEnvelope,
  InterruptedUsage,
  RunAttachment,
  RunHistory,
  RunStatus,
  TodoItem,
  UsageData,
} from "../../api/types";
import { errorKindOf } from "./retry";

export type ChatItem =
  // attachments：随这条消息发出的文件（没有附件时不带这个字段）
  | { kind: "user"; id: string; text: string; attachments?: RunAttachment[] }
  | { kind: "assistant"; id: string; text: string }
  // 思考的起止（设计 2026-10-22 3.4，显示"思考了 N 秒"）：从上一个事件算起，到思考之后第一个别的事件为止
  | { kind: "thinking"; id: string; text: string; startedAt?: string; endedAt?: string }
  | {
      kind: "tool";
      id: string;
      name: string;
      args: Record<string, unknown>;
      // waiting：等你审批（approval.required 里有它的调用 ID）
      status: "running" | "waiting" | "success" | "error";
      output: string;
      // 起止时间取自事件时间（工具行显示用时）；waited：等过审批，用时里有等你的时间
      startedAt?: string;
      finishedAt?: string;
      waited?: boolean;
      // 真正开始执行的时间（审批之后，设计 2026-10-23 5.7）：有它时用时从它算起；旧历史没有
      runningAt?: string;
      // 执行命令的真实退出码与错误输出（设计 2026-10-23 5.4）；旧历史没有
      exitCode?: number;
      stderr?: string;
    }
  | {
      // 子智能体：items 是它内部的回答、思考、工具调用等（agent_path 指向它的事件）
      kind: "subagent";
      id: string;
      name: string;
      description: string;
      status: "running" | "success" | "error";
      output: string;
      items: ChatItem[];
    }
  | { kind: "todos"; id: string; todos: TodoItem[] }
  | { kind: "usage"; id: string; usage: UsageData }
  // 智能体在 outputs/ 里生成的文件（产物），fileId 用于下载
  | { kind: "file"; id: string; fileId: string; path: string; size: number; mediaType: string }
  // 智能体用 remember 记下的一条记忆（显示"已记住：xxx"）
  | { kind: "memory"; id: string; content: string; pinned: boolean; suspicious?: string }
  // 运行中插的话（设计 2026-10-23 6.3）：显示在送达的位置，属于这一轮，不切开这一轮；
  // undelivered：这一轮结束时还没送达（失败、被停），留在这一轮末尾（审查 Minor 9）
  | { kind: "interjection"; id: string; text: string; undelivered?: boolean }
  // 一轮运行的开始 / 结束时间（取自开始、结束事件），用于显示耗时；
  // 等待审批的时间（pausedMs，pausedAt 为正在等待的开始时间）不算进耗时
  | {
      kind: "timing";
      id: string;
      startedAt: string;
      finishedAt?: string;
      pausedMs?: number;
      pausedAt?: string;
    }
  | ApprovalItem
  // interruptedUsage：被中断那次模型调用的估算用量（只显示，不计入合计）
  | { kind: "stopped"; id: string; interruptedUsage?: InterruptedUsage }
  // "重试这一轮"后，失败的那一轮收成一行：第几次失败、原因（D26）
  | { kind: "retried"; id: string; attempt: number; text: string }
  // 运行失败（发送、停止请求本身失败不算：它们显示在输入框上方，不进对话）
  | {
      kind: "error";
      id: string;
      text: string;
      runId: string;
      errorKind: ErrorKind; // 失败的类型（设计 2026-10-23 4.5），报错卡片按它给按钮
      retryable: boolean; // 能否"重试这一轮"（D26）
      interruptedUsage?: InterruptedUsage;
    };

/**
 * 一次审批暂停（设计文档 10.5）：等你决定（pending）→ 提交中（submitting）→ 已处理（resolved）；
 * 等待时停止了运行为 stopped。seq 是 approval.required 的序号：恢复后从它之后接着订阅推送。
 */
export interface ApprovalItem {
  kind: "approval";
  id: string;
  runId: string;
  seq: number;
  requests: ApprovalRequest[];
  status: "pending" | "submitting" | "resolved" | "stopped";
  answers?: ApprovalAnswer[];
}

export interface ChatState {
  items: ChatItem[];
  running: boolean;
  // 最近一个事件的时间：下一段思考从它算起。界面历史里合并过的思考片段只留下最后一段的时间，
  // 从上一个事件算起，实时与重放才一致（也算上了模型开始输出前的等待）
  clock?: string;
  // 主智能体最近一次调用时的上下文分段（设计 2026-10-23 4.7）；旧历史没有
  context?: ContextUsageData;
  // 已交给后端、还没送达的插话（显示"已排队"）：送达时按原文对上移走，运行结束时清空
  queued?: QueuedInterjection[];
}

export interface QueuedInterjection {
  key: string;
  text: string;
}

export const emptyChat: ChatState = { items: [], running: false };

export function addUserMessage(
  state: ChatState,
  id: string,
  text: string,
  attachments: RunAttachment[] = [],
): ChatState {
  const item: ChatItem =
    attachments.length > 0 ? { kind: "user", id, text, attachments } : { kind: "user", id, text };
  return { ...state, items: [...state.items, item] };
}

/** 插话交给后端时先排上（显示"已排队"）。 */
export function queueInterjection(state: ChatState, key: string, text: string): ChatState {
  return { ...state, queued: [...(state.queued ?? []), { key, text }] };
}

/** 插话没送出去（请求失败）：撤回排队。 */
export function dropQueued(state: ChatState, key: string): ChatState {
  return { ...state, queued: (state.queued ?? []).filter((item) => item.key !== key) };
}

/** 顶栏的"N 轮"按运行次数算：插话不算新的一轮（设计 2026-10-23 6.3）。 */
export function roundCount(state: ChatState): number {
  return state.items.filter((item) => item.kind === "user").length;
}

export function removeItem(state: ChatState, id: string): ChatState {
  return { ...state, items: state.items.filter((item) => item.id !== id) };
}

/** 等你处理的审批（待审批或提交中），没有时为 null。 */
export function pendingApproval(state: ChatState): ApprovalItem | null {
  const item = state.items.findLast((entry) => entry.kind === "approval");
  return item?.kind === "approval" && (item.status === "pending" || item.status === "submitting")
    ? item
    : null;
}

/** 改审批卡片的状态（提交时改为提交中，提交失败时改回待审批）。 */
export function setApprovalStatus(
  state: ChatState,
  id: string,
  status: ApprovalItem["status"],
): ChatState {
  return {
    ...state,
    items: state.items.map((item) =>
      item.kind === "approval" && item.id === id ? { ...item, status } : item,
    ),
  };
}

/** 进程中途退出的运行（没有结束事件）：算"被打断"，不知道中断前做过什么，不能重试。 */
export function addError(state: ChatState, runId: string, text: string): ChatState {
  const error: ChatItem = {
    kind: "error",
    id: `err-${runId}`,
    text,
    runId,
    errorKind: "interrupted",
    retryable: false,
  };
  return { items: [...state.items, error], running: false };
}

/** 事件处理器：输入当前状态和一个事件，输出新状态。实时推送与历史重放共用。 */
export function applyEvent(state: ChatState, event: EventEnvelope): ChatState {
  // 主智能体这一层的其他事件结束正在进行的思考（子智能体那一层由 applyToItems 处理）
  const current =
    event.type === "thinking.delta" || event.agent_path.length > 1
      ? state
      : { ...state, items: closeThinking(state.items, event.ts) };
  return { ...step(current, event), clock: event.ts };
}

function step(state: ChatState, event: EventEnvelope): ChatState {
  switch (event.type) {
    case "run.started": {
      const id = `timing-${event.run_id}`;
      if (state.items.some((item) => item.id === id)) return { ...state, running: true };
      return {
        items: [...state.items, { kind: "timing", id, startedAt: event.ts }],
        running: true,
        ...keepQueued(state),
      };
    }
    case "run.finished":
      return runFinished(state, event);
    case "approval.required":
      return approvalRequired(state, event);
    case "user.interjected": {
      const id = `interject-${event.data.id}`;
      if (state.items.some((item) => item.id === id)) return state;
      const queued = state.queued ?? [];
      const at = queued.findIndex((item) => item.text === event.data.text);
      return {
        ...state,
        items: [...state.items, { kind: "interjection", id, text: event.data.text }],
        ...(at === -1 ? {} : { queued: queued.toSpliced(at, 1) }),
      };
    }
    case "context.usage":
      // 工具条上的"上下文 N%"只看主智能体的（子智能体、压缩各有各的上下文）
      return event.agent_path.length === 1 ? { ...state, context: event.data } : state;
    case "approval.resolved":
      return approvalResolved(state, event);
    default:
      // agent_path 第一段是 main，其后每一段是一层子智能体（派出它的调用 ID）
      return {
        ...state,
        items: applyToItems(state.items, event, event.agent_path.slice(1), state.clock ?? event.ts),
      };
  }
}

type Of<T extends EventEnvelope["type"]> = Extract<EventEnvelope, { type: T }>;

function runFinished(state: ChatState, event: Of<"run.finished">): ChatState {
  const timingId = `timing-${event.run_id}`;
  // 等待审批时停止：卡片显示"已停止，未执行"，等待中的工具卡片回到"未结束"（显示为已中断）
  const items = setToolStatus(state.items, null, "waiting", "running").map((item) =>
    item.kind === "timing" && item.id === timingId
      ? { ...unpause(item, event.ts), finishedAt: event.ts }
      : item.kind === "approval" && (item.status === "pending" || item.status === "submitting")
        ? { ...item, status: "stopped" as const }
        : item,
  );
  const estimate = event.data.interrupted_usage;
  const interrupted = estimate ? { interruptedUsage: estimate } : {};
  // 没送达的插话：页面开着时还会放回输入框；重放历史时只靠这一行让人知道
  for (const [index, text] of (event.data.undelivered ?? []).entries()) {
    items.push({
      kind: "interjection",
      id: `undelivered-${event.run_id}-${index}`,
      text,
      undelivered: true,
    });
  }
  if (event.data.status === "failed") {
    const text = event.data.error ?? "运行失败";
    const error: ChatItem = {
      kind: "error",
      id: `err-${event.run_id}`,
      text,
      runId: event.run_id,
      errorKind: errorKindOf(event.data.error_kind, text),
      retryable: event.data.retryable ?? false, // 旧历史没有：只给"继续"
      ...interrupted,
    };
    return { items: [...items, error], running: false };
  }
  if (event.data.status === "cancelled") {
    const stopped: ChatItem = {
      kind: "stopped",
      id: `stopped-${event.run_id}`,
      ...interrupted,
    };
    return { items: [...items, stopped], running: false };
  }
  return { items, running: false };
}

function approvalRequired(state: ChatState, event: Of<"approval.required">): ChatState {
  const id = `approval-${event.run_id}-${event.seq}`;
  if (state.items.some((item) => item.id === id)) return { ...state, running: false };
  const callIds = new Set(
    event.data.requests.flatMap((request) => request.actions.map((action) => action.call_id)),
  );
  const timingId = `timing-${event.run_id}`;
  const items = setToolStatus(state.items, callIds, "running", "waiting").map((item) =>
    item.kind === "timing" && item.id === timingId ? { ...item, pausedAt: event.ts } : item,
  );
  const approval: ApprovalItem = {
    kind: "approval",
    id,
    runId: event.run_id,
    seq: event.seq,
    requests: event.data.requests,
    status: "pending",
  };
  // 排队的插话留着：恢复后接着送达
  return { items: [...items, approval], running: false, ...keepQueued(state) };
}

function approvalResolved(state: ChatState, event: Of<"approval.resolved">): ChatState {
  const timingId = `timing-${event.run_id}`;
  const index = state.items.findLastIndex(
    (item) =>
      item.kind === "approval" && (item.status === "pending" || item.status === "submitting"),
  );
  const approval = state.items[index];
  const edits = approval?.kind === "approval" ? editedArgs(approval, event.data.answers) : {};
  const resumed = setToolArgs(setToolStatus(state.items, null, "waiting", "running"), edits);
  const items = resumed.map((item, at) => {
    if (at === index && item.kind === "approval") {
      return { ...item, status: "resolved" as const, answers: event.data.answers };
    }
    return item.kind === "timing" && item.id === timingId ? unpause(item, event.ts) : item;
  });
  return { items, running: true, ...keepQueued(state) };
}

/** 换成新状态时带上排队的插话（运行开始、等审批、审批通过都不清掉，审查 Minor 1）。 */
function keepQueued(state: ChatState): Pick<ChatState, "queued"> {
  return state.queued ? { queued: state.queued } : {};
}

/**
 * 结束这一层里还在进行的思考（任何别的事件一到就结束它）。通常是最后一项；同一段思考中间夹进
 * 回答文字后又接着来时，它排在前面，也要结束，否则一直显示"思考中…"。
 */
function closeThinking(items: ChatItem[], ts: string): ChatItem[] {
  // 只看这一轮（最后一条用户消息之后）：更早那几轮没结束的思考（进程中途退出）不该按现在的时间结束
  const from = items.findLastIndex((item) => item.kind === "user") + 1;
  const open = (item: ChatItem, at: number) =>
    at >= from && item.kind === "thinking" && item.endedAt === undefined;
  return items.some(open)
    ? items.map((item, at) =>
        item.kind === "thinking" && open(item, at) ? { ...item, endedAt: ts } : item,
      )
    : items;
}

/** 选了"修改后执行"的调用：调用 ID → 新参数（工具卡片改为显示实际执行的参数）。 */
function editedArgs(
  approval: ApprovalItem,
  answers: ApprovalAnswer[],
): Record<string, Record<string, unknown>> {
  const edits: Record<string, Record<string, unknown>> = {};
  for (const answer of answers) {
    const request = approval.requests.find((r) => r.interrupt_id === answer.interrupt_id);
    (answer.decisions ?? []).forEach((decision, index) => {
      const callId = request?.actions[index]?.call_id;
      if (decision.type === "edit" && decision.args && callId) edits[callId] = decision.args;
    });
  }
  return edits;
}

function setToolArgs(
  items: ChatItem[],
  edits: Record<string, Record<string, unknown>>,
): ChatItem[] {
  if (Object.keys(edits).length === 0) return items;
  return items.map((item) => {
    if (item.kind === "subagent") return { ...item, items: setToolArgs(item.items, edits) };
    const args = item.kind === "tool" ? edits[item.id.slice("tool-".length)] : undefined;
    return item.kind === "tool" && args ? { ...item, args } : item;
  });
}

type TimingItem = Extract<ChatItem, { kind: "timing" }>;

/** 等待审批结束（恢复或停止）：这段等待加进 pausedMs，不算进耗时。 */
function unpause(item: TimingItem, ts: string): TimingItem {
  if (!item.pausedAt) return item;
  const waited = Math.max(0, Date.parse(ts) - Date.parse(item.pausedAt));
  return { ...item, pausedAt: undefined, pausedMs: (item.pausedMs ?? 0) + waited };
}

/**
 * 改工具卡片的状态（含子智能体内部的）：callIds 为 null 时改全部处于 from 的卡片。
 * 调用 ID 全局唯一，所以不必按 agent_path 定位。
 */
function setToolStatus(
  items: ChatItem[],
  callIds: Set<string> | null,
  from: "running" | "waiting",
  to: "running" | "waiting",
): ChatItem[] {
  return items.map((item) => {
    if (item.kind === "subagent") {
      return { ...item, items: setToolStatus(item.items, callIds, from, to) };
    }
    if (
      item.kind === "tool" &&
      item.status === from &&
      (callIds === null || callIds.has(item.id.slice("tool-".length)))
    ) {
      return to === "waiting" ? { ...item, status: to, waited: true } : { ...item, status: to };
    }
    return item;
  });
}

type ItemEvent = Exclude<
  EventEnvelope,
  {
    type:
      | "run.started"
      | "run.finished"
      | "approval.required"
      | "approval.resolved"
      | "context.usage"
      | "user.interjected";
  }
>;

/** since：上一个事件的时间（新的一段思考从它算起）。 */
function applyToItems(
  all: ChatItem[],
  event: ItemEvent,
  path: string[],
  since: string,
): ChatItem[] {
  const [callId, ...rest] = path;
  if (callId !== undefined) {
    return all.map((item) =>
      item.kind === "subagent" && item.id === `sub-${callId}`
        ? { ...item, items: applyToItems(item.items, event, rest, since) }
        : item,
    );
  }
  const items = event.type === "thinking.delta" ? all : closeThinking(all, event.ts);
  switch (event.type) {
    case "message.delta":
      return appendDelta(items, "assistant", `msg-${event.data.message_id}`, event.data);
    case "thinking.delta":
      return appendDelta(items, "thinking", `think-${event.data.message_id}`, event.data, since);
    case "thinking.started": {
      // 思考的真实开始（设计 2026-10-23 4.8）；旧历史没有这个事件，开始时间按上一个事件推算
      const id = `think-${event.data.message_id}`;
      return items.some((item) => item.id === id)
        ? items
        : [...items, { kind: "thinking", id, text: "", startedAt: event.ts }];
    }
    case "thinking.finished": {
      // 真实结束：覆盖期间被别的事件推算出的结束时间
      const id = `think-${event.data.message_id}`;
      return items.map((item) =>
        item.kind === "thinking" && item.id === id ? { ...item, endedAt: event.ts } : item,
      );
    }
    case "tool.started":
      return [
        ...items,
        {
          kind: "tool",
          id: `tool-${event.data.call_id}`,
          name: event.data.name,
          args: event.data.args,
          status: "running",
          output: "",
          startedAt: event.ts,
        },
      ];
    case "tool.running": {
      const id = `tool-${event.data.call_id}`;
      return items.map((item) =>
        item.kind === "tool" && item.id === id ? { ...item, runningAt: event.ts } : item,
      );
    }
    case "tool.finished": {
      const id = `tool-${event.data.call_id}`;
      return items.map((item) =>
        item.kind === "tool" && item.id === id
          ? {
              ...item,
              status: event.data.status,
              output: event.data.output,
              finishedAt: event.ts,
              ...(event.data.exit_code != null ? { exitCode: event.data.exit_code } : {}),
              ...(event.data.stderr ? { stderr: event.data.stderr } : {}),
            }
          : item,
      );
    }
    case "subagent.started":
      return [
        ...items,
        {
          kind: "subagent",
          id: `sub-${event.data.call_id}`,
          name: event.data.name,
          description: event.data.description,
          status: "running",
          output: "",
          items: [],
        },
      ];
    case "subagent.finished": {
      const id = `sub-${event.data.call_id}`;
      return items.map((item) =>
        item.kind === "subagent" && item.id === id
          ? { ...item, status: event.data.status, output: event.data.output }
          : item,
      );
    }
    case "todos.updated": {
      // 同一次运行只保留一份待办清单，原地更新
      const id = `todos-${event.run_id}`;
      const todos: ChatItem = { kind: "todos", id, todos: event.data.todos };
      return items.some((item) => item.id === id)
        ? items.map((item) => (item.id === id ? todos : item))
        : [...items, todos];
    }
    case "usage":
      return [
        ...items,
        { kind: "usage", id: `usage-${event.run_id}-${event.seq}`, usage: event.data },
      ];
    case "file.created": {
      const { file_id: fileId, path, size, media_type: mediaType } = event.data;
      if (!fileId) return items; // backend 推送前总会填上 ID；没有 ID 就无法下载，不显示
      // 同一次运行里同一文件只显示一张卡片，再次改动时原地更新
      const id = `file-${event.run_id}-${fileId}`;
      const file: ChatItem = { kind: "file", id, fileId, path, size, mediaType };
      return items.some((item) => item.id === id)
        ? items.map((item) => (item.id === id ? file : item))
        : [...items, file];
    }
    case "memory.saved":
      return [...items, memoryItem(event.data)];
  }
}

/** "已记住"一项：可疑的带上原因（聊天里标出来，设计 2026-10-23 6.6） */
function memoryItem(data: Of<"memory.saved">["data"]): ChatItem {
  const { item_id: itemId, content, pinned, suspicious } = data;
  const memory = { kind: "memory" as const, id: `memory-${itemId}`, content, pinned };
  return suspicious ? { ...memory, suspicious } : memory;
}

/**
 * 逐字片段：按 ID 接在同一段内容后面（中间夹了用量等事件也不拆开）；
 * full_text 为 true 时（界面历史里合并过的片段，text 是到此为止的全文）整体替换。
 */
function appendDelta(
  items: ChatItem[],
  kind: "assistant" | "thinking",
  id: string,
  data: { text: string; full_text?: boolean },
  startedAt?: string,
): ChatItem[] {
  const index = items.findLastIndex((item) => item.id === id);
  const existing = items[index];
  if (existing?.kind !== kind) {
    return [
      ...items,
      kind === "thinking"
        ? { kind, id, text: data.text, startedAt }
        : { kind, id, text: data.text },
    ];
  }
  const text = data.full_text ? data.text : existing.text + data.text;
  if (existing.kind === "thinking") {
    // 中间夹了别的事件后同一段思考又接着来：重新算作进行中，结束时间等下一个别的事件
    return items.with(index, { kind, id, text, startedAt: existing.startedAt });
  }
  return items.with(index, { ...existing, text });
}

const ACTIVE_STATUSES = new Set<RunStatus>(["queued", "running", "interrupted"]);

/**
 * 界面历史里进行中的运行（页面打开时它还在跑）：推送从最后一个已存事件之后接着订阅，
 * 已存的部分已由界面历史重建，从头订阅会让文字重复。
 */
export function activeRun(runs: RunHistory[]): { id: string; afterSeq: number } | null {
  // 等待审批的运行停在 approval.required：没有推送可接，等你在卡片上决定后再订阅
  const run = runs.find(
    (item) =>
      ACTIVE_STATUSES.has(item.status) &&
      !(item.status === "interrupted" && item.events.at(-1)?.type === "approval.required"),
  );
  return run ? { id: run.id, afterSeq: run.events.at(-1)?.seq ?? 0 } : null;
}

/**
 * 由界面历史（每次运行的用户消息 + 已存事件）重建对话状态。
 * "重试这一轮"发起的运行（retry_of）不再显示用户消息，被重试的那一轮收成一行（D26）。
 */
export function chatFromHistory(runs: RunHistory[]): ChatState {
  const starts = new Map<string, number>(); // 运行 ID → 它自己的内容从第几项开始
  return runs.reduce((state, run) => {
    const from = run.retry_of ? starts.get(run.retry_of) : undefined;
    const base =
      from === undefined
        ? addUserMessage(state, `user-${run.id}`, run.message, run.attachments)
        : collapseRetried(state, from, run.retry_of ?? "");
    starts.set(run.id, base.items.length);
    const replayed = run.events.reduce(applyEvent, base);
    // 进程在运行途中退出时没有存下结束事件，只能从运行状态得知失败原因
    const ended = run.events.some((event) => event.type === "run.finished");
    return run.status === "failed" && !ended
      ? addError(replayed, run.id, run.error ?? "运行失败")
      : replayed;
  }, emptyChat);
}

/** 被重试的那一轮（from 之后的全部项）换成一行"第 N 次失败：原因"。 */
function collapseRetried(state: ChatState, from: number, runId: string): ChatState {
  const failed = state.items.slice(from);
  const error = failed.find((item) => item.kind === "error");
  const earlier = state.items.slice(0, from);
  let attempt = 1;
  for (let index = earlier.length - 1; earlier[index]?.kind === "retried"; index -= 1) attempt += 1;
  const line: ChatItem = {
    kind: "retried",
    id: `retried-${runId}`,
    attempt,
    text: error?.kind === "error" ? error.text : "已停止",
  };
  return { ...state, items: [...earlier, line] };
}
