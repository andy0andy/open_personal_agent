import { useEffect, useRef, useState } from "react";

/**
 * 复制文字。优先用浏览器的剪贴板接口；非安全环境（用 http 访问非本机地址）里浏览器不提供它，
 * 被拒绝时也一样——这两种情况退回到"隐藏文本框 + 复制命令"。都不行时返回 false。
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (typeof navigator.clipboard !== "undefined") {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // 被拒绝：试试退路
  }
  return copyWithTextArea(text);
}

function copyWithTextArea(text: string): boolean {
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  Object.assign(area.style, { position: "fixed", top: "0", opacity: "0", pointerEvents: "none" });
  document.body.appendChild(area);
  try {
    area.select();
    // 已不推荐使用，但不安全的页面上只有它能复制
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    area.remove();
  }
}

export type CopyState = "idle" | "copied" | "failed";

/** 复制按钮的状态：复制后显示 1.5 秒"已复制"或"复制失败"；连续点击重新计时，组件卸载时清掉计时器。 */
export function useCopy(): { state: CopyState; copy: (text: string) => void } {
  const [state, setState] = useState<CopyState>("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = (text: string) => {
    void copyText(text).then((ok) => {
      clearTimeout(timer.current);
      setState(ok ? "copied" : "failed");
      timer.current = setTimeout(() => setState("idle"), 1500);
    });
  };
  return { state, copy };
}
