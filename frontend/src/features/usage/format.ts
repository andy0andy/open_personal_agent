/** token 数：超过一千用 k、超过一百万用 M，保留一位小数（整数时不带小数）。 */
export function formatTokens(tokens: number): string {
  if (tokens < 1000) return String(tokens);
  const [value, unit] = tokens < 1_000_000 ? [tokens / 1000, "k"] : [tokens / 1_000_000, "M"];
  return `${Number(value.toFixed(1))}${unit}`;
}

/** 一轮对话的耗时（完成后）：一分钟内保留一位小数，之后用"分 秒"、"小时 分"。 */
export function formatDuration(ms: number): string {
  const seconds = ms / 1000;
  if (seconds < 60) return `${Number(seconds.toFixed(1))} 秒`;
  const total = Math.round(seconds);
  if (total < 3600) return `${Math.floor(total / 60)} 分 ${total % 60} 秒`;
  return `${Math.floor(total / 3600)} 小时 ${Math.floor((total % 3600) / 60)} 分`;
}

/** 运行中的已用时间：按整秒显示。 */
export function formatElapsed(ms: number): string {
  const total = Math.floor(ms / 1000);
  return total < 60 ? `${total} 秒` : formatDuration(total * 1000);
}
