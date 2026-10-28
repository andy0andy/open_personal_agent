import type { WorkspaceFile } from "../../api/types";

/** 输入框上方待发送的文件：选中后立即上传，上传完成的随下一条消息作为附件发出。 */
export interface PendingUpload {
  key: string; // 页面生成，区分同名文件
  name: string;
  size: number;
  status: "uploading" | "done" | "failed";
  file?: WorkspaceFile; // 上传完成后的登记信息
  error?: string;
}

export function startUpload(
  list: PendingUpload[],
  key: string,
  name: string,
  size: number,
): PendingUpload[] {
  return [...list, { key, name, size, status: "uploading" }];
}

export function finishUpload(
  list: PendingUpload[],
  key: string,
  file: WorkspaceFile,
): PendingUpload[] {
  return list.map((item) => (item.key === key ? { ...item, status: "done", file } : item));
}

export function failUpload(list: PendingUpload[], key: string, error: string): PendingUpload[] {
  return list.map((item) => (item.key === key ? { ...item, status: "failed", error } : item));
}

export function removeUpload(list: PendingUpload[], key: string): PendingUpload[] {
  return list.filter((item) => item.key !== key);
}

/** 发送时附带的文件（上传失败的不带）；还有文件在上传时返回 null，要等它传完。 */
export function readyAttachments(list: PendingUpload[]): WorkspaceFile[] | null {
  if (list.some((item) => item.status === "uploading")) return null;
  return list.flatMap((item) => (item.file ? [item.file] : []));
}

/**
 * 粘贴板里要当作附件上传的文件（如截图）；没有时照常粘贴文字。从 Excel、Word 等复制内容时，
 * 粘贴板里文字之外还附一张那段内容的图：有文字、文件又都是图片时按文字粘贴，不上传那张图。
 */
export function pastedFiles(data: Pick<DataTransfer, "files" | "types">): File[] {
  const files = [...data.files];
  const hasText = data.types.includes("text/plain") || data.types.includes("text/html");
  if (hasText && files.every((file) => file.type.startsWith("image/"))) return [];
  return files;
}

/**
 * 每个上传一个 AbortController：移除还在传的附件时中止它（积压小问题 D6）；中止后上传请求
 * 失败，不再标成"上传失败"。后端在请求中断时会删掉半截文件。
 */
export function uploadAborts() {
  const controllers = new Map<string, AbortController>();
  return {
    signal(key: string): AbortSignal {
      const controller = new AbortController();
      controllers.set(key, controller);
      return controller.signal;
    },
    abort(key: string): void {
      controllers.get(key)?.abort();
      controllers.delete(key);
    },
    done(key: string): void {
      controllers.delete(key);
    },
  };
}
