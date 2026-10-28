import type { PermissionMode } from "../../api/types";

/** 会话审批权限的一档：标题、一行说明、颜色（风险越大越醒目）。 */
export interface PermissionOption {
  value: PermissionMode;
  title: string;
  description: string;
  tone: "default" | "warning" | "danger";
}

const ASK: PermissionOption = {
  value: "ask",
  title: "每次先问",
  description: "执行命令先问你；外部工具按 MCP 页的审批规则",
  tone: "default",
};

/** 三档（D23），从稳妥到放开；新会话为第一档。 */
export const PERMISSIONS: readonly PermissionOption[] = [
  ASK,
  {
    value: "ask_execute",
    title: "只问执行命令",
    description: "只有执行命令先问你，其余全部自动",
    tone: "warning",
  },
  {
    value: "skip",
    title: "跳过所有审批",
    description: "什么都不问（危险命令除外），直接执行，包括命令",
    tone: "danger",
  },
];

/** 运行中或等待审批时改了档位：这次运行仍用开始时的档位（D23）。 */
export const PENDING_HINT = "从下一条消息开始生效";

export function permissionOption(value: PermissionMode): PermissionOption {
  return PERMISSIONS.find((option) => option.value === value) ?? ASK;
}
