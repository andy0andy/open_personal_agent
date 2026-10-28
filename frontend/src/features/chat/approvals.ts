import type { ApprovalAction, ApprovalAnswer, ToolDecision } from "../../api/types";
import { toolLabel } from "../../components/chat/tools";
import type { ApprovalItem } from "./reducer";

/**
 * 审批卡片上对一个操作的选择（设计文档 7.5 的四种）：同意、修改参数后执行（text 是编辑框里的 JSON）、
 * 拒绝、回复一句话（调用不执行，这句话转给智能体）。
 */
export type Choice =
  | { type: "approve" }
  | { type: "edit"; text: string }
  | { type: "reject" }
  | { type: "reply"; message: string };

/** "回复一句话"的长度上限（与后端 ToolDecision.message 一致）。 */
export const REPLY_LIMIT = 2000;

/** 一个操作在选择表里的键：第几处暂停的第几个操作。 */
export function choiceKey(interruptId: string, index: number): string {
  return `${interruptId}/${index}`;
}

/** 编辑框里的参数：必须是一个 JSON 对象。 */
export function parseEditedArgs(
  text: string,
): { ok: true; args: Record<string, unknown> } | { ok: false; error: string } {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return { ok: false, error: "不是合法的 JSON：检查引号、逗号和括号是否成对" };
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return { ok: false, error: "参数应是一个对象（用 { } 括起来）" };
  }
  return { ok: true, args: value as Record<string, unknown> };
}

/** 全部操作都选好（且修改的参数合法、回复不为空）时给出提交的答复，否则为 null。 */
export function toAnswers(
  item: ApprovalItem,
  choices: Record<string, Choice>,
): ApprovalAnswer[] | null {
  const answers: ApprovalAnswer[] = [];
  for (const request of item.requests) {
    const decisions: ToolDecision[] = [];
    for (const [index] of request.actions.entries()) {
      const decision = toDecision(choices[choiceKey(request.interrupt_id, index)]);
      if (!decision) return null;
      decisions.push(decision);
    }
    answers.push({ interrupt_id: request.interrupt_id, decisions });
  }
  return answers;
}

function toDecision(choice: Choice | undefined): ToolDecision | null {
  switch (choice?.type) {
    case "approve":
      return { type: "approve" };
    case "reject":
      return { type: "reject" };
    case "edit": {
      const parsed = parseEditedArgs(choice.text);
      return parsed.ok ? { type: "edit", args: parsed.args } : null;
    }
    case "reply": {
      const message = choice.message.trim();
      return message && message.length <= REPLY_LIMIT ? { type: "reject", message } : null;
    }
    default:
      return null;
  }
}

/** 这个调用实际执行（或将要执行）的参数：选了"修改后执行"时是新参数。 */
export function executedArgs(
  action: ApprovalAction,
  decision: ToolDecision | undefined,
): Record<string, unknown> {
  return decision?.type === "edit" && decision.args ? decision.args : action.args;
}

/** 已处理的审批里每个决定的说明。 */
export function choiceLabel(decision: ToolDecision): string {
  switch (decision.type) {
    case "approve":
      return "已同意";
    case "edit":
      return "已修改参数后执行";
    case "reject":
      return decision.message ? `已回复：${decision.message}` : "已拒绝";
  }
}

/**
 * 审批卡片的标题（设计 2026-10-22 3.6）：执行命令问"要执行这条命令吗？"；外部工具写出服务与工具名；
 * 内置工具用中文动词（参数在下面的等宽块里）。
 */
export function approvalTitle(action: ApprovalAction): string {
  const { verb, detail, kind } = toolLabel(action.name, action.args);
  if (kind === "execute") return "要执行这条命令吗？";
  if (kind === "external") return `要调用 ${detail} 吗？`;
  if (kind === "other") return `要调用 ${action.name} 吗？`;
  return `要${verb}吗？`;
}

const DANGER_PREFIX = "危险操作：";

/** 命中了硬底线的命令（设计 2026-10-23 5.2）：后端在说明里写"危险操作：…"，取出命中的那一条。 */
export function dangerOf(action: ApprovalAction): string | null {
  return action.description.startsWith(DANGER_PREFIX)
    ? action.description.slice(DANGER_PREFIX.length)
    : null;
}

/** 审批处理完以后，工具行上显示的决定（沿用 choiceLabel 的说法）。 */
export interface DecisionView {
  label: string;
  tone: "success" | "danger" | "muted";
  /** 选了"修改后执行"：实际执行的参数 */
  editedArgs?: Record<string, unknown>;
}

export const STOPPED_DECISION: DecisionView = { label: "已停止，未执行", tone: "muted" };

export function decisionView(action: ApprovalAction, decision: ToolDecision): DecisionView {
  const label = choiceLabel(decision);
  switch (decision.type) {
    case "approve":
      return { label, tone: "success" };
    case "edit":
      return { label, tone: "success", editedArgs: executedArgs(action, decision) };
    case "reject":
      return { label, tone: decision.message ? "muted" : "danger" };
  }
}
