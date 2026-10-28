import { useEffect, useRef, type RefObject } from "react";
import { closesOverlay, isTopLayer, popLayer, pushLayer } from "./escape";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** 在对话框里按 Tab：下一个要聚焦的是第几项（到头从另一头接着来）；没有可聚焦的时为 -1（停在对话框本身）。 */
export function nextFocusIndex(current: number, count: number, backwards: boolean): number {
  if (count === 0) return -1;
  if (current < 0) return backwards ? count - 1 : 0;
  return (current + (backwards ? -1 : 1) + count) % count;
}

/**
 * 关闭后焦点回到谁：打开前的焦点已是 body 或已不在页面上（从菜单打开时，菜单项随菜单一起被移除）
 * 时，用 fallback 给的（审查 Minor 3）。
 */
export function focusAfterClose(
  previous: HTMLElement | null,
  fallback: HTMLElement | null | undefined,
  body: HTMLElement,
): HTMLElement | null {
  if (previous && previous !== body && previous.isConnected) return previous;
  return fallback ?? previous;
}

/**
 * 对话框、抽屉的键盘操作（积压小问题 H1）：打开时把焦点移进去（pickInitial 给的，没有就是第一个
 * 可聚焦的元素，再没有就是对话框本身，它要带 tabIndex=-1）；Tab 在里面循环；Esc 关闭；
 * 都只管最上面那一层；关闭后焦点回到打开它的那个元素（它已不在时回到 returnFocus 给的）。
 */
export function useDialog(
  open: boolean,
  onClose: () => void,
  dialog: RefObject<HTMLElement | null>,
  pickInitial?: () => HTMLElement | null | undefined,
  returnFocus?: () => HTMLElement | null | undefined,
): void {
  const close = useRef(onClose);
  const pick = useRef(pickInitial);
  const back = useRef(returnFocus);
  useEffect(() => {
    close.current = onClose;
    pick.current = pickInitial;
    back.current = returnFocus;
  });
  useEffect(() => {
    if (!open) return;
    const layer = pushLayer();
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const root = dialog.current;
    const items = () => [...(root?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
    (pick.current?.() ?? items()[0] ?? root)?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (!isTopLayer(layer)) return;
      if (closesOverlay(event)) {
        event.preventDefault();
        close.current();
      } else if (event.key === "Tab") {
        event.preventDefault();
        const all = items();
        const next = nextFocusIndex(
          all.indexOf(document.activeElement as HTMLElement),
          all.length,
          event.shiftKey,
        );
        (next >= 0 ? all[next] : root)?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      popLayer(layer);
      focusAfterClose(previous, back.current?.(), document.body)?.focus();
    };
  }, [open, dialog]);
}
