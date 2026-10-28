/** 会话搜索（设计 2026-10-23 6.1）：标题即时过滤，停顿后再查内容；结果分"标题匹配"与"内容里提到"。 */

/** 停止输入多久后查内容（毫秒）。 */
export const SEARCH_DELAY_MS = 300;

export interface HighlightPart {
  text: string;
  hit: boolean;
}

/** 查询里用空格分开的几个词（服务器没给命中词时用它加粗）。 */
export function queryWords(query: string): string[] {
  return query.trim().split(/\s+/).filter(Boolean);
}

/**
 * 把片段切成"命中词 / 其余文字"几段，命中词加粗显示；不分大小写。词用服务器给的命中词
 * （按分词命中，积压小问题 B4），没有时用 queryWords。
 */
export function highlightParts(text: string, terms: string[]): HighlightPart[] {
  const words = [...terms]
    .filter(Boolean)
    .sort((a, b) => b.length - a.length) // 长词优先：同一处既能匹配长词又能匹配短词时取长的
    .map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (words.length === 0) return [{ text, hit: false }];
  const parts: HighlightPart[] = [];
  let last = 0;
  for (const match of text.matchAll(new RegExp(words.join("|"), "giu"))) {
    if (match.index > last) parts.push({ text: text.slice(last, match.index), hit: false });
    parts.push({ text: match[0], hit: true });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), hit: false });
  return parts;
}

/** 服务器按标题找到、本地即时过滤里没有的会话（如已归档的），补在标题匹配的后面。 */
export function extraTitleMatches<T extends { id: string }>(local: T[], server: T[]): T[] {
  const shown = new Set(local.map((thread) => thread.id));
  return server.filter((thread) => !shown.has(thread.id));
}

/** 内容里提到的那一轮：打开那个会话并滚到这一轮。 */
export function hitLink(hit: { thread_id: string; run_id: string }): string {
  return `/chat/${hit.thread_id}?run=${hit.run_id}`;
}
