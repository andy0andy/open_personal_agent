import type { QueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { threadsQuery } from "../../api/queries";

const REORDER = ["reorder-threads"];

/** 拖动排序的保存（积压小问题 B1）：界面先按新顺序排好，保存在后台进行。 */
export function reorderMutation(
  queryClient: QueryClient,
  save: (threadIds: string[]) => Promise<unknown> = api.reorderThreads,
) {
  return {
    mutationKey: REORDER,
    mutationFn: save,
    // 正在进行的列表刷新可能带回旧顺序，覆盖刚排好的界面：先取消它
    onMutate: () => queryClient.cancelQueries({ queryKey: threadsQuery.queryKey }),
    // 最后一次保存结束后以服务器为准（失败时即恢复原来的顺序）；连续拖动时中途不刷新，免得来回跳。
    // 把刷新交回去：等它回来才算保存结束，期间轮询带回的旧顺序不会闪一下（审查 Minor 2）
    onSettled: () =>
      queryClient.isMutating({ mutationKey: REORDER }) === 1
        ? queryClient.invalidateQueries({ queryKey: threadsQuery.queryKey })
        : undefined,
  };
}
