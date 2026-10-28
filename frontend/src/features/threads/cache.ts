import type { QueryClient } from "@tanstack/react-query";
import { archivedThreadsQuery, threadQuery, threadsQuery } from "../../api/queries";
import type { Thread } from "../../api/types";

/**
 * 把新建的会话放进会话列表。先取消正在进行的列表刷新：它在新建之前发出，返回的旧列表会把新会话盖掉，
 * 对话页随之以为会话不存在、退回空状态。
 */
export async function addCreatedThread(client: QueryClient, thread: Thread): Promise<void> {
  await client.cancelQueries({ queryKey: threadsQuery.queryKey });
  client.setQueryData<Thread[]>(threadsQuery.queryKey, (old) => [thread, ...(old ?? [])]);
}

/**
 * 改了标题或会话设置后换掉列表里的这一项。运行状态只有列表接口会算（其他接口为空），
 * 保留列表里原来的，免得状态点闪掉、等下一次刷新才回来。先取消正在进行的列表刷新：
 * 它在改之前发出，晚到时会把旧的模型、标题写回（只取消主列表，搜索与归档列表不动）。
 */
export async function replaceThread(client: QueryClient, updated: Thread): Promise<void> {
  await client.cancelQueries({ queryKey: threadsQuery.queryKey, exact: true });
  client.setQueryData<Thread[]>(threadsQuery.queryKey, (old) =>
    (old ?? []).map((item) =>
      item.id === updated.id ? { ...updated, activity: item.activity } : item,
    ),
  );
}

/**
 * 删掉一个会话之后：从会话列表移除；按 ID 取的那份（已归档、搜索点进来的会话靠它显示）重新查，
 * 查不到时对话页随之回到 /chat；归档列表也重新查（审查 I3）。
 */
export function forgetThread(client: QueryClient, threadId: string): void {
  client.setQueryData<Thread[]>(threadsQuery.queryKey, (old) =>
    (old ?? []).filter((item) => item.id !== threadId),
  );
  void client.invalidateQueries({ queryKey: threadQuery(threadId).queryKey });
  void client.invalidateQueries({ queryKey: archivedThreadsQuery.queryKey });
}
