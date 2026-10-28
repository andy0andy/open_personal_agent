import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { archivedThreadsQuery, threadQuery, threadsQuery } from "../../api/queries";
import type { Thread } from "../../api/types";

/**
 * 归档、取消归档（设计 2026-10-23 6.5）：会话列表与顶栏共用。改完后按 ID 取的那份换成新的
 * （正打开的会话不在列表里了也照常显示），主列表、归档列表重新拉。
 */
export function useArchive() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ threadId, archived }: { threadId: string; archived: boolean }) =>
      api.updateThread(threadId, { archived }),
    onSuccess: (thread) => {
      queryClient.setQueryData(threadQuery(thread.id).queryKey, thread);
      void queryClient.invalidateQueries({ queryKey: threadsQuery.queryKey });
    },
  });
}

/** 看过了这个会话：后端记下时间；列表（含归档列表）里它的"有新回答"先清掉，不等下一次刷新。 */
export async function markViewed(client: QueryClient, threadId: string): Promise<void> {
  await api.markViewed(threadId);
  const seen = (old: Thread[] | undefined) =>
    old?.map((item) =>
      item.id === threadId && item.activity === "new" ? { ...item, activity: null } : item,
    );
  client.setQueryData<Thread[]>(threadsQuery.queryKey, seen);
  client.setQueryData<Thread[]>(archivedThreadsQuery.queryKey, seen);
}
