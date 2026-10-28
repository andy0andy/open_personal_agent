/**
 * 回答里的会话链接（设计 2026-10-23 6.1）：智能体照抄 search_conversations 给出的
 * `[《标题》第 N 轮](#conv-<会话 ID>-<运行 ID>)`，点开在本页打开那个会话并滚到那一轮。
 */
const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const CONVERSATION = new RegExp(`^#conv-(${UUID})-(${UUID})$`);

export interface ConversationTarget {
  threadId: string;
  runId: string;
}

export function conversationTarget(href: string | undefined): ConversationTarget | null {
  const match = href?.match(CONVERSATION);
  return match?.[1] && match[2] ? { threadId: match[1], runId: match[2] } : null;
}

export function conversationPath(target: ConversationTarget): string {
  return `/chat/${target.threadId}?run=${target.runId}`;
}

/**
 * 界面上这一轮的用户消息在哪次运行下："重试这一轮"发起的运行没有自己的用户消息
 * （收成一行，D26），沿 retry_of 往回找到原来那次。
 */
export function messageRunOf(
  runId: string,
  runs: readonly { id: string; retry_of?: string | null }[],
): string {
  const byId = new Map(runs.map((run) => [run.id, run]));
  let current = runId;
  for (let step = 0; step < runs.length; step += 1) {
    const previous = byId.get(current)?.retry_of;
    if (!previous) break;
    current = previous;
  }
  return current;
}
