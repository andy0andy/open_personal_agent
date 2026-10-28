import type { SettingView } from "../../api/types";

/** 设置页的分节（D22，设计 2026-10-22 第 4 节）：按设置键的前缀归类；页面上不能改的单独放"只读项"。 */
const SECTIONS: { id: string; title: string; match: (key: string) => boolean }[] = [
  { id: "chat", title: "对话与模型", match: (key) => key.startsWith("agent.") },
  {
    id: "workspace",
    title: "工作区",
    match: (key) => key.startsWith("workspace.") || key === "max_upload_mb",
  },
  { id: "knowledge", title: "知识库", match: (key) => key.startsWith("knowledge.") },
];

export interface SettingSection {
  id: string;
  title: string;
  /** 这一节的生效时机（每节说一次，行内不再重复） */
  note: string;
  items: SettingView[];
}

/**
 * 页面上不能改的项（.env 指定的不算：它们留在原来那节，写明由 .env 的哪个变量指定）；
 * 不属于任何一节的（如 adapters.*、models.sources）一律放这里，否则会整项消失。
 */
const isReadonly = (view: SettingView) =>
  (!view.editable && view.source !== "env") || !SECTIONS.some(({ match }) => match(view.key));

function applyNote(items: SettingView[]): string {
  if (items.every((view) => view.apply === "now")) return "改了立即生效";
  if (items.every((view) => view.apply === "restart")) return "改了重启后生效";
  return "改了重启后生效（标着“立即生效”的除外）";
}

export function groupSettings(views: SettingView[]): SettingSection[] {
  const editable = views.filter((view) => !isReadonly(view));
  const sections: SettingSection[] = SECTIONS.map(({ id, title, match }) => {
    const items = editable.filter((view) => match(view.key));
    return { id, title, note: applyNote(items), items };
  });
  sections.push({
    id: "readonly",
    title: "只读项",
    note: "页面上不能改，原因写在每一项下面",
    items: views.filter(isReadonly),
  });
  return sections.filter((section) => section.items.length > 0);
}

/** 已保存、重启后才生效的项数（页顶提示条）。 */
export function pendingRestartCount(views: SettingView[]): number {
  return views.filter((view) => view.restart_pending).length;
}

/** 这一节有没有待重启的项（分节导航上的琥珀点）。 */
export function sectionPending(views: SettingView[]): boolean {
  return views.some((view) => view.restart_pending);
}

/** 行内徽章：改过的项标"已改"，还要重启才生效的标"已改 · 待重启"（琥珀）。 */
export function rowBadge(view: SettingView): { text: string; tone: "warning" | "default" } | null {
  if (view.restart_pending) return { text: "已改 · 待重启", tone: "warning" };
  return view.source === "db" ? { text: "已改", tone: "default" } : null;
}

/** 输入框里的文字 → 要保存的值：数字项（当前值是数字）要填合法数字。 */
export function parseInput(
  view: SettingView,
  raw: string,
): { ok: true; value: unknown } | { ok: false; error: string } {
  const text = raw.trim();
  if (typeof view.value === "number") {
    const value = Number(text);
    return text !== "" && Number.isFinite(value)
      ? { ok: true, value }
      : { ok: false, error: "请填数字" };
  }
  return { ok: true, value: text };
}

/** 上传上限（MB，设置项 max_upload_mb）：技能上传、文档上传的提示与预查都用它；还没取到时为空。 */
export function uploadLimitMb(views: SettingView[] | undefined): number | null {
  const value = views?.find((view) => view.key === "max_upload_mb")?.value;
  return typeof value === "number" ? value : null;
}
