import { LoaderCircle, Paperclip, TriangleAlert, X } from "lucide-react";
import { useRef } from "react";
import type { PendingUpload } from "../../features/chat/uploads";
import { formatSize } from "../format";

/** 输入框里的"添加附件"按钮：可一次选多个文件。 */
export function AttachButton({ onAddFiles }: { onAddFiles: (files: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <button
        type="button"
        aria-label="添加附件"
        title="添加附件（也可以把文件拖进对话区）"
        className="flex size-9 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
        onClick={() => input.current?.click()}
      >
        <Paperclip className="size-4" />
      </button>
      <input
        ref={input}
        type="file"
        multiple
        hidden
        onChange={(event) => {
          onAddFiles([...(event.target.files ?? [])]);
          event.target.value = ""; // 同一个文件可以再选一次
        }}
      />
    </>
  );
}

/** 输入框上方待发送的文件：上传中转圈，失败显示原因，都可以移除。 */
export function UploadChips({
  uploads,
  onRemove,
}: {
  uploads: PendingUpload[];
  onRemove: (key: string) => void;
}) {
  if (uploads.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-1.5 px-1 pb-1">
      {uploads.map((upload) => (
        <li
          key={upload.key}
          title={upload.error ?? upload.name}
          className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs ${
            upload.status === "failed" ? "border-danger/40 text-danger" : "border-border"
          }`}
        >
          {upload.status === "uploading" && <LoaderCircle className="size-3.5 animate-spin" />}
          {upload.status === "failed" && <TriangleAlert className="size-3.5" />}
          {upload.status === "done" && <Paperclip className="size-3.5 text-muted-foreground" />}
          <span className="max-w-48 truncate">{upload.name}</span>
          <span className="text-muted-foreground">
            {upload.status === "failed" ? upload.error : formatSize(upload.size)}
          </span>
          <button
            type="button"
            aria-label={`移除 ${upload.name}`}
            className="rounded p-0.5 hover:bg-muted"
            onClick={() => onRemove(upload.key)}
          >
            <X className="size-3" />
          </button>
        </li>
      ))}
    </ul>
  );
}
