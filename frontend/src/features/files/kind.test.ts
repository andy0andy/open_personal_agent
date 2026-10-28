import { describe, expect, it } from "vitest";
import type { WorkspaceFile } from "../../api/types";
import { groupFiles, previewKind } from "./kind";

const file = (path: string, media_type: string, size = 10): WorkspaceFile => ({
  id: path,
  thread_id: "t1",
  path,
  source: path.startsWith("uploads/") ? "upload" : "output",
  media_type,
  size,
  created_at: "2026-10-15T00:00:00Z",
  updated_at: "2026-10-15T00:00:00Z",
});

describe("按文件类型选择预览方式", () => {
  it("图片、表格、PDF、Markdown、网页各有预览", () => {
    expect(previewKind(file("outputs/a.png", "image/png"))).toBe("image");
    expect(previewKind(file("outputs/a.svg", "image/svg+xml"))).toBe("image");
    expect(previewKind(file("uploads/a.csv", "text/csv"))).toBe("table");
    expect(previewKind(file("uploads/a.TSV", "text/tab-separated-values"))).toBe("table");
    const xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    expect(previewKind(file("outputs/报表.xlsx", xlsx))).toBe("table");
    expect(previewKind(file("outputs/a.pdf", "application/pdf"))).toBe("pdf");
    expect(previewKind(file("outputs/a.md", "text/markdown"))).toBe("markdown");
    expect(previewKind(file("outputs/a.html", "text/html"))).toBe("html");
  });

  it("文字与代码直接显示原文；太大的、其他类型只能下载", () => {
    expect(previewKind(file("outputs/a.py", "text/x-python"))).toBe("text");
    expect(previewKind(file("outputs/a.json", "application/json"))).toBe("text");
    expect(previewKind(file("outputs/log.txt", "text/plain", 2 * 1024 * 1024))).toBe("none");
    expect(previewKind(file("uploads/a.docx", "application/vnd.ms-word"))).toBe("none");
    expect(previewKind(file("uploads/a.bin", "application/octet-stream"))).toBe("none");
  });
});

describe("文件面板的分组", () => {
  it("上传与产物分开，各自保持原来的顺序", () => {
    const files = [
      file("outputs/b.png", "image/png"),
      file("uploads/a.csv", "text/csv"),
      file("outputs/c.md", "text/markdown"),
    ];
    const groups = groupFiles(files);
    expect(groups.uploads.map((f) => f.path)).toEqual(["uploads/a.csv"]);
    expect(groups.outputs.map((f) => f.path)).toEqual(["outputs/b.png", "outputs/c.md"]);
  });
});

describe("常见的文字文件与浏览器显示不了的图片（积压小问题 D3）", () => {
  it(".log / .yaml / .ts 即使类型未知也按文字显示（不超过 1MB）", () => {
    for (const path of ["outputs/run.log", "outputs/conf.yaml", "outputs/a.ts", "outputs/x.toml"]) {
      expect(previewKind(file(path, "application/octet-stream"))).toBe("text");
    }
    expect(previewKind(file("outputs/big.log", "application/octet-stream", 2 * 1024 * 1024))).toBe(
      "none",
    );
    expect(previewKind(file("outputs/a.bin", "application/octet-stream"))).toBe("none");
  });

  it(".heic / .tiff 只能下载（浏览器显示不了，不显示破图）", () => {
    expect(previewKind(file("uploads/a.heic", "image/heic"))).toBe("none");
    expect(previewKind(file("uploads/a.tiff", "image/tiff"))).toBe("none");
    expect(previewKind(file("uploads/a.png", "image/png"))).toBe("image");
  });
});
