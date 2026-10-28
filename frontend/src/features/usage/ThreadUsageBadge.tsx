import { useQuery } from "@tanstack/react-query";
import { Gauge } from "lucide-react";
import { threadUsageQuery } from "../../api/queries";
import { formatTokens } from "./format";

/**
 * 工具条：本会话累计用量（含标题生成、记忆整理等后台调用）；悬停显示按模型版本的拆分。
 * 上下文占比挪到了旁边的 ContextMeter（设计 2026-10-23 4.7）。
 */
export function ThreadUsageBadge({ threadId }: { threadId: string }) {
  const usage = useQuery(threadUsageQuery(threadId));
  const total = usage.data?.total;
  if (!total || total.calls === 0) return null;
  const details = (usage.data?.by_model ?? [])
    .map(
      (model) =>
        `${model.model}：${model.calls} 次，输入 ${formatTokens(model.input_tokens)}，` +
        `输出 ${formatTokens(model.output_tokens)}`,
    )
    .join("\n");
  const amount = `${formatTokens(total.input_tokens + total.output_tokens)} token`;
  return (
    <span
      className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground"
      title={`本会话共 ${amount}\n${details}`}
    >
      <Gauge className="size-3.5" aria-hidden="true" />
      <span className="hidden whitespace-nowrap @md:inline">
        <span className="font-mono">{amount}</span>
      </span>
    </span>
  );
}
