import { describe, expect, it } from "vitest";
import type { WorkspaceFile } from "../../api/types";
import {
  failUpload,
  finishUpload,
  pastedFiles,
  readyAttachments,
  removeUpload,
  startUpload,
  uploadAborts,
} from "./uploads";

const record = (id: string): WorkspaceFile => ({
  id,
  thread_id: "t1",
  path: `uploads/${id}.csv`,
  source: "upload",
  media_type: "text/csv",
  size: 3,
  created_at: "2026-10-15T00:00:00Z",
  updated_at: "2026-10-15T00:00:00Z",
});

describe("输入框上方待发送的文件", () => {
  it("选中即开始上传；完成、失败按各自的标识更新，同名文件互不影响", () => {
    let list = startUpload([], "k1", "a.csv", 3);
    list = startUpload(list, "k2", "a.csv", 5);
    list = finishUpload(list, "k1", record("f1"));
    list = failUpload(list, "k2", "文件超过 100MB 上限");
    expect(list).toEqual([
      { key: "k1", name: "a.csv", size: 3, status: "done", file: record("f1") },
      { key: "k2", name: "a.csv", size: 5, status: "failed", error: "文件超过 100MB 上限" },
    ]);
    expect(removeUpload(list, "k2").map((item) => item.key)).toEqual(["k1"]);
  });

  it("发送时只带上传完成的文件；还有文件在上传时要等它传完", () => {
    let list = startUpload([], "k1", "a.csv", 3);
    expect(readyAttachments(list)).toBeNull();
    list = finishUpload(list, "k1", record("f1"));
    list = failUpload(startUpload(list, "k2", "b.csv", 3), "k2", "上传失败");
    expect(readyAttachments(list)).toEqual([record("f1")]);
    expect(readyAttachments([])).toEqual([]);
  });
});

describe("粘贴", () => {
  const list = (...files: File[]) => files as unknown as FileList;

  it("粘贴板里只有文件（如截图）：当作附件", () => {
    const shot = new File(["png"], "image.png", { type: "image/png" });
    expect(pastedFiles({ files: list(shot), types: ["Files"] })).toEqual([shot]);
  });

  it("只是文字：没有文件，照常粘贴", () => {
    expect(pastedFiles({ files: list(), types: ["text/plain"] })).toEqual([]);
  });

  it("从 Excel、Word 复制的内容（文字之外还带一张图）：按文字粘贴，不上传那张图", () => {
    const picture = new File(["png"], "image.png", { type: "image/png" });
    expect(
      pastedFiles({ files: list(picture), types: ["text/plain", "text/html", "Files"] }),
    ).toEqual([]);
  });

  it("复制的文件不是图片：照样当附件（哪怕同时带着文件名文字）", () => {
    const pdf = new File(["%PDF"], "a.pdf", { type: "application/pdf" });
    expect(pastedFiles({ files: list(pdf), types: ["text/plain", "Files"] })).toEqual([pdf]);
  });
});

describe("移除还在传的附件（积压小问题 D6）", () => {
  it("只中止那一个上传；传完的不再记着", () => {
    const aborts = uploadAborts();
    const first = aborts.signal("u1");
    const second = aborts.signal("u2");
    aborts.abort("u1");
    expect(first.aborted).toBe(true);
    expect(second.aborted).toBe(false);
    aborts.done("u2");
    aborts.abort("u2"); // 已经传完：没有可中止的
    expect(second.aborted).toBe(false);
  });
});
