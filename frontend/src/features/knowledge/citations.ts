/**
 * 回答里的出处链接（设计文档 8.3）：智能体照抄检索结果给出的 `[《文档名》位置](#kb-<条目 ID>)`，
 * 前端把这种链接显示成可点的出处按钮。其他链接照常是链接。
 */
const CITATION = /^#kb-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/;

/** 出处链接指向的条目 ID；不是出处链接（含编号格式不对）时为 null。 */
export function citationTarget(href: string | undefined): string | null {
  return href?.match(CITATION)?.[1] ?? null;
}

/** 回答里一个链接的显示方式：出处按钮；格式不对的出处按普通文字显示（不在新标签页打开应用）；普通链接。 */
export function linkKind(href: string | undefined): "citation" | "broken-citation" | "link" {
  if (citationTarget(href) !== null) return "citation";
  return href?.startsWith("#kb-") ? "broken-citation" : "link";
}
