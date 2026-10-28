import type { KnowledgeDocument } from "../../api/types";

/** 知识库能处理的文件（与后端 SUPPORTED_SUFFIXES 一致）。 */
export const DOCUMENT_SUFFIXES = [
  ".pdf",
  ".docx",
  ".pptx",
  ".xlsx",
  ".csv",
  ".md",
  ".markdown",
  ".txt",
  ".html",
  ".htm",
];

/** 会话里的这个文件能不能加入知识库（按后缀；图片、老格式 Office 文件不能）。 */
export function canJoinKnowledge(path: string): boolean {
  const lower = path.toLowerCase();
  return DOCUMENT_SUFFIXES.some((suffix) => lower.endsWith(suffix));
}

export interface StatusText {
  text: string;
  tone: "muted" | "warning" | "danger";
}

/** 文档处理状态的说明：处理中带进度，失败带原因。 */
export function documentStatus(document: KnowledgeDocument): StatusText {
  switch (document.status) {
    case "pending":
      return { text: "等待处理", tone: "muted" };
    case "processing":
      return {
        text:
          document.chunk_total > 0
            ? `处理中 ${document.item_count} / ${document.chunk_total} 段`
            : "处理中",
        tone: "warning",
      };
    case "done":
      return { text: `已完成 · ${document.item_count} 段`, tone: "muted" };
    case "failed":
      return { text: `失败：${document.error ?? "原因未知"}`, tone: "danger" };
  }
}

/** 有文档在等待或处理时每 2 秒刷新列表（看得到进度），全部结束后停止。 */
export function pollWhileProcessing(documents: KnowledgeDocument[] | undefined): number | false {
  const busy = documents?.some((doc) => doc.status === "pending" || doc.status === "processing");
  return busy ? 2000 : false;
}

/** 文档原文的地址；有页码时加 #page=N，浏览器的 PDF 阅读器会跳到该页。 */
export function documentContentUrl(documentId: string, page: number | null): string {
  const url = `/api/knowledge/documents/${documentId}/content`;
  return page === null ? url : `${url}#page=${page}`;
}

/** 片段在文档里的位置：章节路径、页码（与智能体给出的出处写法一致）。 */
export function chunkLocation(item: { section_path: string | null; page: number | null }): string {
  const page = item.page === null ? null : `第 ${item.page} 页`;
  return [item.section_path, page].filter(Boolean).join(" · ");
}
