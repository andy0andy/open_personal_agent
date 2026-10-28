/**
 * 输入法正在选字时按下的键：回车只是确认候选词（不能当成"保存"），Esc 只是取消候选词（不能当成"关闭"）。
 * Chrome 用 isComposing 表示；Safari 在选字确认时 isComposing 已为 false，但 keyCode 为 229。
 */
export function isImeComposing(event: { isComposing: boolean; keyCode: number }): boolean {
  return event.isComposing || event.keyCode === 229;
}
