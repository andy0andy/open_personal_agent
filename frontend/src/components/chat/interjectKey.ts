import { isImeComposing } from "../ime";

/**
 * 运行中按下的键要不要拦下来送插话（设计 2026-10-23 6.3）：assistant-ui 运行中不处理回车，
 * 由我们先拦下。输入法选字时的回车只是确认候选词（Safari 确认时 isComposing 已为 false，审查 Minor 2）。
 */
export function sendsInterjection(
  event: { key: string; shiftKey: boolean; nativeEvent: { isComposing: boolean; keyCode: number } },
  canInterject: boolean,
): boolean {
  return (
    canInterject && event.key === "Enter" && !event.shiftKey && !isImeComposing(event.nativeEvent)
  );
}
