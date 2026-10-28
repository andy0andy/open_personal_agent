import { useEffect, useRef } from "react";
import { isImeComposing } from "../ime";

// 打开着的抽屉、对话框按打开顺序排队：按 Esc、Tab 只管最上面那一层（如抽屉里再弹出的删除确认框）
const layers: symbol[] = [];

/** 打开一层弹层，返回它的标识；关掉时交给 popLayer。 */
export function pushLayer(): symbol {
  const id = Symbol("overlay");
  layers.push(id);
  return id;
}

export function popLayer(id: symbol): void {
  const index = layers.indexOf(id);
  if (index >= 0) layers.splice(index, 1);
}

/** 这一层是不是最上面那一层。 */
export function isTopLayer(id: symbol): boolean {
  return layers.at(-1) === id;
}

export function closesOverlay(event: {
  key: string;
  isComposing: boolean;
  keyCode: number;
}): boolean {
  return event.key === "Escape" && !isImeComposing(event);
}

export function useEscape(active: boolean, onEscape: () => void): void {
  const handler = useRef(onEscape);
  useEffect(() => {
    handler.current = onEscape;
  });
  useEffect(() => {
    if (!active) return;
    const id = pushLayer();
    const onKey = (event: KeyboardEvent) => {
      if (closesOverlay(event) && isTopLayer(id)) {
        event.preventDefault();
        handler.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      popLayer(id);
    };
  }, [active]);
}
