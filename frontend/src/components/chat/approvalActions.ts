import { createContext } from "react";
import type { ApprovalAnswer } from "../../api/types";
import type { ApprovalItem } from "../../features/chat/reducer";

/** 审批卡片可用的动作（由页面提供）：提交决定。停止用输入框旁的停止按钮。 */
export interface ApprovalActions {
  answer: (item: ApprovalItem, answers: ApprovalAnswer[]) => void;
}

export const ApprovalActionsContext = createContext<ApprovalActions>({
  answer: () => {},
});
