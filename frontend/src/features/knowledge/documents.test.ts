import { describe, expect, it } from "vitest";
import type { KnowledgeDocument } from "../../api/types";
import {
  canJoinKnowledge,
  chunkLocation,
  documentContentUrl,
  documentStatus,
  pollWhileProcessing,
} from "./documents";

const base = {
  id: "d1",
  title: "员工手册",
  filename: "员工手册.docx",
  media_type: "application/octet-stream",
  size: 10,
  error: null,
  chunk_total: 0,
  item_count: 0,
  source_thread_id: null,
  created_at: "2026-10-16T00:00:00Z",
  updated_at: "2026-10-16T00:00:00Z",
} satisfies Omit<KnowledgeDocument, "status">;

describe("documentStatus", () => {
  it("等待、处理中（带进度）、完成、失败（带原因）", () => {
    expect(documentStatus({ ...base, status: "pending" })).toEqual({
      text: "等待处理",
      tone: "muted",
    });
    expect(documentStatus({ ...base, status: "processing" })).toEqual({
      text: "处理中",
      tone: "warning",
    });
    expect(
      documentStatus({ ...base, status: "processing", chunk_total: 30, item_count: 12 }),
    ).toEqual({ text: "处理中 12 / 30 段", tone: "warning" });
    expect(documentStatus({ ...base, status: "done", chunk_total: 30, item_count: 30 })).toEqual({
      text: "已完成 · 30 段",
      tone: "muted",
    });
    expect(
      documentStatus({ ...base, status: "failed", error: "没有提取到文字：可能是扫描件" }),
    ).toEqual({ text: "失败：没有提取到文字：可能是扫描件", tone: "danger" });
  });
});

describe("pollWhileProcessing", () => {
  it("有文档在等待或处理时每 2 秒刷新，全部结束后停止", () => {
    const done = { ...base, status: "done" as const };
    expect(pollWhileProcessing([done, { ...base, status: "processing" }])).toBe(2000);
    expect(pollWhileProcessing([done, { ...base, status: "pending" }])).toBe(2000);
    expect(pollWhileProcessing([done, { ...base, status: "failed" }])).toBe(false);
    expect(pollWhileProcessing(undefined)).toBe(false);
  });
});

describe("documentContentUrl", () => {
  it("原文地址；有页码时 PDF 阅读器跳到该页", () => {
    expect(documentContentUrl("d1", 3)).toBe("/api/knowledge/documents/d1/content#page=3");
    expect(documentContentUrl("d1", null)).toBe("/api/knowledge/documents/d1/content");
  });
});

describe("chunkLocation", () => {
  it("章节路径与页码（与回答里出处的写法一致）", () => {
    expect(chunkLocation({ section_path: "第一章 考勤 › 1.1 请假", page: 3 })).toBe(
      "第一章 考勤 › 1.1 请假 · 第 3 页",
    );
    expect(chunkLocation({ section_path: null, page: 3 })).toBe("第 3 页");
    expect(chunkLocation({ section_path: null, page: null })).toBe("");
  });
});

describe("canJoinKnowledge", () => {
  it("只有知识库能处理的格式才显示加入知识库", () => {
    expect(canJoinKnowledge("outputs/报告.PDF")).toBe(true);
    expect(canJoinKnowledge("uploads/sales.xlsx")).toBe(true);
    expect(canJoinKnowledge("uploads/chart.png")).toBe(false);
    expect(canJoinKnowledge("uploads/old.doc")).toBe(false);
  });
});
