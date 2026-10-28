import type { SkillInfo } from "../../api/types";
import { relativeTime } from "../threads/activity";

const FRONT_MATTER = "SKILL.md 开头要有 --- 包起来的 name 与 description";
const UNSUPPORTED = "只能上传技能文件夹、.zip 或 SKILL.md";

/**
 * 读 SKILL.md 开头的 name 与 description（只认一行一个"键: 值"；预览用，真正的解析在后端
 * agents/main_agent/runtime/skills.py）。
 */
export function parseSkillMd(
  text: string,
): { name: string; description: string } | { error: string } {
  const lines = text.split(/\r?\n/);
  if (lines[0]?.trim() !== "---") return { error: FRONT_MATTER };
  const end = lines.findIndex((line, index) => index > 0 && line.trim() === "---");
  if (end === -1) return { error: FRONT_MATTER };
  const fields: Record<string, string> = {};
  for (const line of lines.slice(1, end)) {
    const match = /^([A-Za-z_]+):\s*(.*)$/.exec(line);
    if (match?.[1]) fields[match[1]] = (match[2] ?? "").trim().replace(/^["']|["']$/g, "");
  }
  if (!fields.name) return { error: "SKILL.md 开头缺少 name" };
  if (!fields.description) return { error: "SKILL.md 开头缺少 description" };
  return { name: fields.name, description: fields.description };
}

/** path 带文件夹层级（选择文件夹时浏览器给的相对路径）；只有 SKILL.md 读出了 text；size 是字节数 */
export type UploadFile = { path: string; text?: string; size?: number };

/** 上传前先查的上限：与后端一致（单个技能最多 500 个文件，合计不超过设置里的上传上限）。 */
export interface UploadLimits {
  maxFiles: number;
  maxBytes: number;
}

export type UploadResult =
  | { kind: "ok"; name: string; description: string; fileCount: number }
  | { kind: "zip"; fileName: string }
  | { kind: "error"; message: string };

const baseName = (path: string) => path.split("/").at(-1) ?? path;

/** Mac 打包、选文件夹时夹带的 __MACOSX/ 与 .DS_Store：后端先去掉它们再数文件、算大小，这里照做 */
const isMacMetadata = (path: string) =>
  path.split("/").includes("__MACOSX") || baseName(path) === ".DS_Store";

/** 识别上传的东西：单个 SKILL.md、含 SKILL.md 的文件夹（取最浅的那个），或压缩包（预览里不解析）。 */
export function inspectUpload(
  files: UploadFile[],
  existingNames: string[],
  limits?: UploadLimits,
): UploadResult {
  const [first] = files;
  if (!first) return { kind: "error", message: UNSUPPORTED };
  const tooBig =
    limits &&
    checkLimits(
      files.filter((file) => !isMacMetadata(file.path)),
      limits,
    );
  if (tooBig) return { kind: "error", message: tooBig };
  const single = files.length === 1 && !first.path.includes("/");
  if (single && first.path.toLowerCase().endsWith(".zip")) {
    return { kind: "zip", fileName: first.path };
  }
  if (single && baseName(first.path) !== "SKILL.md") return { kind: "error", message: UNSUPPORTED };
  const skillFiles = files
    .filter((file) => baseName(file.path) === "SKILL.md")
    .sort((a, b) => a.path.split("/").length - b.path.split("/").length);
  const skill = skillFiles[0];
  if (!skill) return { kind: "error", message: "文件夹里没有 SKILL.md" };
  if (skill.text === undefined) return { kind: "error", message: "读不出 SKILL.md 的内容" };
  const parsed = parseSkillMd(skill.text);
  if ("error" in parsed) return { kind: "error", message: parsed.error };
  // 不许同名（D21）；Mac 的文件系统不分大小写，Excel 和 excel 是同一个文件夹
  const taken = existingNames.find((name) => name.toLowerCase() === parsed.name.toLowerCase());
  if (taken) return { kind: "error", message: `已有同名技能「${taken}」，换个名字再上传` };
  return {
    kind: "ok",
    name: parsed.name,
    description: parsed.description,
    fileCount: files.filter((file) => !isMacMetadata(file.path)).length,
  };
}

export type SkillFilter = "all" | "enabled" | "disabled";

export function filterSkills(skills: SkillInfo[], filter: SkillFilter, query: string): SkillInfo[] {
  const words = query.trim().toLowerCase();
  return skills.filter(
    (skill) =>
      (filter === "all" || skill.enabled === (filter === "enabled")) &&
      (!words || `${skill.name}\n${skill.description}`.toLowerCase().includes(words)),
  );
}

/** 技能页的最近使用时间（取自技能用量，设计 2026-10-23 7.7）：今天写几点，更早的写哪天。 */
export function lastUsedLabel(lastUsedAt: string | null | undefined, now: Date): string {
  return lastUsedAt ? `最近使用：${relativeTime(lastUsedAt, now)}` : "从未使用";
}

/** 上传后说明太长时的提示：长度以后端的检查为准（前端只粗略解析了说明头）。 */
export function uploadedNotice(skill: SkillInfo): string | null {
  return skill.notice ? `已上传「${skill.name}」。${skill.notice}` : null;
}

/** 文件太多、合计太大时的原因（不用传上去才被拒绝，积压小问题 F6）；没超时为空。 */
function checkLimits(files: UploadFile[], { maxFiles, maxBytes }: UploadLimits): string | null {
  if (files.length > maxFiles) return `文件太多：一个技能最多 ${maxFiles} 个文件`;
  const total = files.reduce((sum, file) => sum + (file.size ?? 0), 0);
  if (total > maxBytes) {
    return `文件太大：合计超过上传上限 ${Math.round(maxBytes / 1024 / 1024)}MB`;
  }
  return null;
}

/** 上传后的提示：只在那个技能还在时显示（删掉后不再留着，积压小问题 F1）。 */
export function visibleNotice(
  notice: { id: string; text: string } | null,
  skills: SkillInfo[],
): string | null {
  return notice && skills.some((skill) => skill.id === notice.id) ? notice.text : null;
}

/** 停用清单（skills.yaml）写坏时的原因（设置页同一个接口）；正常或还没有这个文件时为空。 */
export function skillsStateError(
  files: { path: string; state: string; detail?: string | null }[],
): string | null {
  const file = files.find((item) => item.path.endsWith("skills.yaml") && item.state === "error");
  return file ? (file.detail ?? `${file.path} 有误`) : null;
}
