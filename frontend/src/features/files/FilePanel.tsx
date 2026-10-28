import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BookPlus, Check, FileText, Image, LoaderCircle, Sheet, X } from "lucide-react";
import { api, readableError } from "../../api/client";
import { filesQuery, refreshKnowledge } from "../../api/queries";
import type { WorkspaceFile } from "../../api/types";
import { fileName, formatSize } from "../../components/format";
import { FilePreview } from "./FilePreview";
import { canJoinKnowledge } from "../knowledge/documents";
import { groupFiles, previewKind } from "./kind";

interface FilePanelProps {
  threadId: string;
  /** 正在预览的文件；null 时显示文件列表。 */
  selectedId: string | null;
  onSelect: (fileId: string | null) => void;
  onClose: () => void;
}

/** 右侧文件面板（设计文档 13.3）：本会话上传与生成的文件，点开即预览。 */
export function FilePanel({ threadId, selectedId, onSelect, onClose }: FilePanelProps) {
  const files = useQuery(filesQuery(threadId));
  const selected = files.data?.find((file) => file.id === selectedId) ?? null;
  return (
    <aside className="flex w-[28rem] max-w-[50%] shrink-0 flex-col border-l border-border bg-card/60">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        {selected ? (
          <button
            className="flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
            onClick={() => onSelect(null)}
          >
            <ArrowLeft className="size-4 shrink-0" />
            全部文件
          </button>
        ) : (
          <span className="font-medium">文件</span>
        )}
        <button
          aria-label="收起文件面板"
          className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          onClick={onClose}
        >
          <X className="size-4" />
        </button>
      </div>
      {files.isError ? (
        <p className="p-4 text-sm text-danger">文件列表加载失败：{readableError(files.error)}</p>
      ) : !files.data ? (
        <p className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" />
          加载中…
        </p>
      ) : selected ? (
        <FilePreview key={selected.id} file={selected} />
      ) : (
        <FileList threadId={threadId} files={files.data} onSelect={onSelect} />
      )}
    </aside>
  );
}

function FileList({
  threadId,
  files,
  onSelect,
}: {
  threadId: string;
  files: WorkspaceFile[];
  onSelect: (fileId: string) => void;
}) {
  if (files.length === 0) {
    return (
      <p className="p-4 text-sm text-muted-foreground">
        还没有文件。上传的文件和智能体生成的文件都会出现在这里。
      </p>
    );
  }
  const { uploads, outputs } = groupFiles(files);
  return (
    <div className="flex-1 space-y-4 overflow-y-auto p-3">
      {[
        { title: "上传的文件", items: uploads },
        { title: "生成的文件", items: outputs },
      ]
        .filter((group) => group.items.length > 0)
        .map((group) => (
          <section key={group.title}>
            <h3 className="mb-1 px-2 text-xs text-muted-foreground">{group.title}</h3>
            <ul>
              {group.items.map((file) => (
                <FileRow key={file.id} threadId={threadId} file={file} onSelect={onSelect} />
              ))}
            </ul>
          </section>
        ))}
    </div>
  );
}

/** 把会话里的文件加入知识库（所有会话都能检索到；后台处理，进度在知识库页的"文档"里）。 */
/** 文件列表的一行：点开预览；知识库能处理的格式可以"加入知识库"，失败原因写在行内。 */
function FileRow({
  threadId,
  file,
  onSelect,
}: {
  threadId: string;
  file: WorkspaceFile;
  onSelect: (fileId: string) => void;
}) {
  const queryClient = useQueryClient();
  const add = useMutation({
    mutationFn: () => api.addFileToKnowledge(threadId, file.id),
    onSuccess: () => refreshKnowledge(queryClient),
  });
  return (
    <li>
      <div className="flex items-center gap-1">
        <button
          className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted"
          title={file.path}
          onClick={() => onSelect(file.id)}
        >
          <KindIcon file={file} />
          <span className="truncate">{fileName(file.path)}</span>
          <span className="ml-auto shrink-0 text-xs text-muted-foreground">
            {formatSize(file.size)}
          </span>
        </button>
        {canJoinKnowledge(file.path) && (
          <AddToKnowledge
            pending={add.isPending}
            done={add.isSuccess}
            failed={add.isError}
            onAdd={() => add.mutate()}
          />
        )}
      </div>
      {add.isError && (
        <p className="px-2 pb-1 text-xs text-danger">加入知识库失败：{readableError(add.error)}</p>
      )}
    </li>
  );
}

function AddToKnowledge({
  pending,
  done,
  failed,
  onAdd,
}: {
  pending: boolean;
  done: boolean;
  failed: boolean;
  onAdd: () => void;
}) {
  if (done) {
    return (
      <span
        className="flex shrink-0 items-center gap-1 px-1.5 text-xs text-success"
        title="已加入知识库"
      >
        <Check className="size-3.5" />
        已加入
      </span>
    );
  }
  return (
    <button
      className="shrink-0 rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
      title="加入知识库（所有会话都能检索到）"
      aria-label="加入知识库"
      disabled={pending}
      onClick={onAdd}
    >
      {pending ? (
        <LoaderCircle className="size-3.5 animate-spin" />
      ) : (
        <BookPlus className={`size-3.5 ${failed ? "text-danger" : ""}`} />
      )}
    </button>
  );
}

function KindIcon({ file }: { file: WorkspaceFile }) {
  const kind = previewKind(file);
  const Icon = kind === "image" ? Image : kind === "table" ? Sheet : FileText;
  return <Icon className="size-4 shrink-0 text-muted-foreground" />;
}
