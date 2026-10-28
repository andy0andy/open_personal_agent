import type { QueryClient } from "@tanstack/react-query";
import { threadsQuery } from "../../api/queries";
import type { PermissionMode, Thread, ThreadCreate, ThreadCreated } from "../../api/types";
import { addCreatedThread } from "../threads/cache";

export interface NewChatDeps {
  createThread: (input: Partial<ThreadCreate>) => Promise<ThreadCreated>;
}

/**
 * 落地页发第一条消息（设计 2026-10-22 3.11）：发送时才建会话。一次请求完成（设计 2026-10-23 6.4）：
 * 后端建好会话、设好模型与权限、发起运行，中途失败就删掉刚建的会话再报原因——这里直接抛出，
 * 字留在落地页，不会留下空会话。model 为空（模型列表还没加载）时不带，用新会话的默认模型。
 */
export async function startNewChat(
  input: { text: string; model: string; permission: PermissionMode },
  deps: NewChatDeps,
): Promise<ThreadCreated> {
  return deps.createThread({
    message: input.text,
    ...(input.model ? { model: input.model } : {}),
    permission_mode: input.permission,
  });
}

/**
 * 落地页建好会话以后：先放进会话列表（对话页才找得到它），再让列表马上刷新——
 * 标题（首条消息）与"运行中"的状态点都由列表接口算，不刷新就要等这一轮跑完。
 */
export async function rememberNewThread(client: QueryClient, thread: Thread): Promise<void> {
  await addCreatedThread(client, thread);
  void client.invalidateQueries({ queryKey: threadsQuery.queryKey });
}
