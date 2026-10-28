import type { McpServerView, ToolApproval } from "../../api/types";

const STATES: Record<McpServerView["state"], string> = {
  disabled: "未启用",
  connecting: "连接中",
  connected: "已连接",
  reconnecting: "重连中",
  failed: "连接失败",
};

export function serverStateLabel(state: McpServerView["state"]): string {
  return STATES[state];
}

export function actionLabel(action: ToolApproval["action"]): string {
  return action === "auto" ? "自动执行" : "先问你";
}
