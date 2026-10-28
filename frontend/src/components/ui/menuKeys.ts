import type { KeyboardEvent } from "react";

/** 菜单里按上下方向键：下一个要聚焦的是第几项（到头从另一头接着来）；不是方向键或没有项时为空。 */
export function nextIndex(current: number, count: number, key: string): number | null {
  if (count === 0 || (key !== "ArrowDown" && key !== "ArrowUp")) return null;
  const step = key === "ArrowDown" ? 1 : -1;
  if (current < 0) return step === 1 ? 0 : count - 1;
  return (current + step + count) % count;
}

/** 在菜单（role="menu"）上按方向键时把焦点移到上一项或下一项；处理了就返回 true。 */
export function moveMenuFocus(event: KeyboardEvent<HTMLElement>): boolean {
  const items = [...event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]')];
  const current = items.indexOf(document.activeElement as HTMLElement);
  const next = nextIndex(current, items.length, event.key);
  if (next === null) return false;
  event.preventDefault();
  items[next]?.focus();
  return true;
}
