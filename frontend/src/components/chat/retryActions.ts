import { createContext } from "react";
import type { ModelChoice } from "../../features/chat/retry";

/**
 * 报错卡片上的动作（由页面提供，设计 2026-10-23 4.5，D26）：重试这一轮（从运行前的存档分叉重跑）、
 * 继续（发一句"继续"）、换个模型（先改会话的模型，能重试就重试、否则继续）。
 * models：会话可选的对话模型；current：会话当前的模型。
 */
export interface RetryActions {
  retry: (runId: string) => void;
  continueTurn: () => void;
  switchModel: (model: string, runId: string, retryable: boolean) => void;
  models: ModelChoice[];
  current: string;
}

export const RetryActionsContext = createContext<RetryActions>({
  retry: () => {},
  continueTurn: () => {},
  switchModel: () => {},
  models: [],
  current: "",
});
