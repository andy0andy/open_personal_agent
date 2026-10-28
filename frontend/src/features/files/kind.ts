import type { WorkspaceFile } from "../../api/types";

/** 文件面板里的预览方式（设计文档 9.3）；none 表示只能下载。 */
export type PreviewKind = "image" | "table" | "pdf" | "markdown" | "html" | "text" | "none";

const TABLE_SUFFIXES = [".csv", ".tsv", ".xlsx", ".xlsm"];
const TEXT_TYPES = new Set(["application/json", "application/xml", "application/javascript"]);
// 后端认不出类型（给成 application/octet-stream）的常见文字文件：按后缀当文字显示
const TEXT_SUFFIXES = [
  ".log",
  ".yaml",
  ".yml",
  ".toml",
  ".ini",
  ".cfg",
  ".conf",
  ".env",
  ".ts",
  ".tsx",
  ".jsx",
  ".vue",
  ".go",
  ".rs",
  ".java",
  ".kt",
  ".swift",
  ".rb",
  ".php",
  ".sql",
  ".sh",
  ".lua",
  ".r",
];
// 浏览器显示不了的图片：只能下载，免得显示一张破图
const UNSHOWN_IMAGES = new Set(["image/heic", "image/heif", "image/tiff"]);
const MAX_TEXT_BYTES = 1024 * 1024; // 更大的文字文件不在页面里显示，请下载查看

export function previewKind(
  file: Pick<WorkspaceFile, "path" | "media_type" | "size">,
): PreviewKind {
  const path = file.path.toLowerCase();
  const type = file.media_type;
  if (UNSHOWN_IMAGES.has(type) || /\.(heic|heif|tiff?)$/.test(path)) return "none";
  if (type.startsWith("image/")) return "image";
  if (TABLE_SUFFIXES.some((suffix) => path.endsWith(suffix))) return "table";
  if (type === "application/pdf") return "pdf";
  if (type === "text/html") return "html";
  const isText =
    type.startsWith("text/") ||
    TEXT_TYPES.has(type) ||
    TEXT_SUFFIXES.some((suffix) => path.endsWith(suffix));
  if (!isText || file.size > MAX_TEXT_BYTES) return "none";
  return type === "text/markdown" ? "markdown" : "text";
}

/** 面板里分两组：用户上传的、智能体生成的（接口返回时已按路径排好）。 */
export function groupFiles(files: WorkspaceFile[]): {
  uploads: WorkspaceFile[];
  outputs: WorkspaceFile[];
} {
  return {
    uploads: files.filter((file) => file.source === "upload"),
    outputs: files.filter((file) => file.source === "output"),
  };
}
