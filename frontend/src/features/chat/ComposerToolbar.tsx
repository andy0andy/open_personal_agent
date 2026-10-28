import type { PermissionMode } from "../../api/types";
import { ModelSelect } from "../models/ModelSelect";
import { ThreadUsageBadge } from "../usage/ThreadUsageBadge";
import { ContextMeter } from "./ContextMeter";
import type { ContextView } from "./context";
import { PermissionSelect } from "./PermissionSelect";

/**
 * 输入框下方的工具条（设计 2026-10-22 3.10）：左边是审批权限；右边是"本会话 token · 上下文 N%"与模型。
 * "文件"挪到了顶栏。工具条本身窄（窗口窄或开着右侧面板）时右边只留图标，全称在 title 里：按容器宽度判断。
 */
export function ComposerToolbar({
  threadId,
  permission,
  onPermission,
  pendingHint,
  model,
  onModel,
  context,
}: {
  threadId: string;
  permission: PermissionMode;
  onPermission: (value: PermissionMode) => void;
  pendingHint: boolean;
  model: string;
  onModel: (model: string) => void;
  /** "上下文 N%"与分段（设计 2026-10-23 4.7），算不出来时为空 */
  context: ContextView | null;
}) {
  return (
    <div className="@container mt-2 flex items-center justify-between gap-3 px-1">
      <PermissionSelect value={permission} onChange={onPermission} pendingHint={pendingHint} />
      <div className="flex min-w-0 items-center gap-2 @md:gap-3">
        <ThreadUsageBadge threadId={threadId} />
        {context && <ContextMeter label={context.label} usage={context.usage} />}
        <ModelSelect value={model} onChange={onModel} />
      </div>
    </div>
  );
}
