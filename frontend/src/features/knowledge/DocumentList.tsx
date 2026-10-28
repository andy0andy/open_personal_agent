import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FileText, LoaderCircle, RotateCw, Trash2, Upload } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { api, readableError } from "../../api/client";
import { appSettingsQuery, documentsQuery, refreshKnowledge } from "../../api/queries";
import type { KnowledgeDocument } from "../../api/types";
import { uploadLimitMb } from "../settings/settings";
import { formatSize } from "../../components/format";
import {
  DOCUMENT_SUFFIXES,
  documentContentUrl,
  documentStatus,
  type StatusText,
} from "./documents";

const ACCEPT = DOCUMENT_SUFFIXES.join(",");
const TONES: Record<StatusText["tone"], string> = {
  muted: "text-muted-foreground",
  warning: "text-warning",
  danger: "text-danger",
};
const ICON_BUTTON =
  "rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40";

/** 知识库文档：上传（选择或拖入，可多选）、处理进度、打开原文、重新处理、删除。 */
export function DocumentList() {
  const queryClient = useQueryClient();
  const documents = useQuery(documentsQuery);
  const limitMb = uploadLimitMb(useQuery(appSettingsQuery).data);
  const [uploading, setUploading] = useState<{ key: number; name: string }[]>([]);
  const [failures, setFailures] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const uploadSeq = useRef(0);

  const upload = (files: File[]) => {
    setFailures([]);
    for (const file of files) {
      uploadSeq.current += 1;
      const key = uploadSeq.current;
      setUploading((current) => [...current, { key, name: file.name }]);
      api
        .uploadDocument(file)
        .then(
          () => refreshKnowledge(queryClient),
          (error: unknown) =>
            setFailures((current) => [...current, `${file.name}：${readableError(error)}`]),
        )
        .finally(() => setUploading((current) => current.filter((item) => item.key !== key)));
    }
  };
  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    upload(Array.from(event.dataTransfer.files));
  };

  return (
    <div className="space-y-3">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-5 text-sm ${
          dragging ? "border-ring bg-muted" : "border-border bg-card"
        }`}
      >
        <button
          className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-primary-foreground"
          onClick={() => input.current?.click()}
        >
          <Upload className="size-3.5" />
          上传文档
        </button>
        <p className="text-xs text-muted-foreground">
          或把文件拖到这里。支持 PDF、Word、PowerPoint、Excel、CSV、Markdown、TXT、网页，单个不超过
          {limitMb ? `${limitMb}MB` : "上传上限"}；处理在后台进行，约 1～2 秒一段。
        </p>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          onChange={(event) => {
            upload(Array.from(event.target.files ?? []));
            event.target.value = "";
          }}
        />
      </div>
      {failures.map((failure) => (
        <p key={failure} className="text-xs text-danger">
          上传失败：{failure}
        </p>
      ))}
      <ul className="space-y-2">
        {uploading.map((item) => (
          <li
            key={item.key}
            className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm text-muted-foreground"
          >
            <LoaderCircle className="size-3.5 animate-spin" />
            {item.name} 上传中…
          </li>
        ))}
        {documents.data?.map((document) => (
          <DocumentRow key={document.id} document={document} />
        ))}
      </ul>
      {documents.isError && (
        <p className="text-sm text-danger">文档列表加载失败：{readableError(documents.error)}</p>
      )}
      {documents.data?.length === 0 && uploading.length === 0 && (
        <p className="text-sm text-muted-foreground">还没有上传文档</p>
      )}
    </div>
  );
}

function DocumentRow({ document }: { document: KnowledgeDocument }) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const refresh = () => refreshKnowledge(queryClient);
  const reprocess = useMutation({
    mutationFn: () => api.reprocessDocument(document.id),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => api.deleteDocument(document.id),
    onSuccess: refresh,
  });
  const status = documentStatus(document);
  const busy = document.status === "pending" || document.status === "processing";
  const error = reprocess.error ?? remove.error;
  return (
    <li className="rounded-lg border border-border bg-card px-3 py-2.5 text-sm">
      <div className="flex items-center gap-2">
        <FileText className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 truncate" title={document.filename}>
          {document.title}
        </span>
        <span className="shrink-0 text-xs text-muted-foreground">{formatSize(document.size)}</span>
        <span className="ml-auto flex shrink-0 items-center gap-0.5">
          <a
            href={documentContentUrl(document.id, null)}
            target="_blank"
            rel="noopener noreferrer"
            className={ICON_BUTTON}
            title="打开原文"
            aria-label="打开原文"
          >
            <ExternalLink className="size-3.5" />
          </a>
          <button
            className={ICON_BUTTON}
            title="重新处理"
            aria-label="重新处理"
            disabled={busy || reprocess.isPending}
            onClick={() => reprocess.mutate()}
          >
            <RotateCw className="size-3.5" />
          </button>
          <button
            className={ICON_BUTTON}
            title="删除"
            aria-label="删除"
            onClick={() => setConfirming(true)}
          >
            <Trash2 className="size-3.5" />
          </button>
        </span>
      </div>
      <p className={`mt-1 flex items-center gap-1.5 text-xs ${TONES[status.tone]}`}>
        {busy && <LoaderCircle className="size-3 animate-spin" />}
        {status.text}
      </p>
      {confirming && (
        <div className="mt-2 flex items-center gap-2">
          <span className="text-danger">删除这份文档？它的片段会一起删除，无法恢复。</span>
          <button
            className="rounded-md bg-danger px-2.5 py-0.5 text-primary-foreground hover:opacity-90 disabled:opacity-50"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
          >
            删除
          </button>
          <button
            className="rounded-md border border-border px-2.5 py-0.5 hover:bg-muted"
            onClick={() => {
              setConfirming(false);
              remove.reset();
            }}
          >
            取消
          </button>
        </div>
      )}
      {error && <p className="mt-1.5 text-xs text-danger">操作失败：{readableError(error)}</p>}
    </li>
  );
}
