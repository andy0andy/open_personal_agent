/** 把 dragged 移到 target 的上方（before）或下方（after），返回新的顺序；拖到自己或目标不存在时不变。 */
export function moveItem(
  ids: string[],
  dragged: string,
  target: string,
  place: "before" | "after",
): string[] {
  if (dragged === target || !ids.includes(dragged) || !ids.includes(target)) return ids;
  const rest = ids.filter((id) => id !== dragged);
  const index = rest.indexOf(target) + (place === "after" ? 1 : 0);
  return [...rest.slice(0, index), dragged, ...rest.slice(index)];
}

/** 两个顺序是否相同（拖完放回原处时不必保存）。 */
export function sameOrder(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((id, index) => id === b[index]);
}

/**
 * 保存中的顺序（积压小问题 B1）：保存还没回来时，轮询可能带回旧顺序把界面盖掉——按正在保存的顺序排，
 * 不在里面的（刚新建的）放最前，已删掉的跳过。
 */
export function pendingOrder<T extends { id: string }>(items: T[], ids: string[]): T[] {
  const byId = new Map(items.map((item) => [item.id, item]));
  const saved = new Set(ids);
  return [
    ...items.filter((item) => !saved.has(item.id)),
    ...ids.flatMap((id) => byId.get(id) ?? []),
  ];
}
