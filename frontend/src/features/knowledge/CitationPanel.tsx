import { useQuery } from "@tanstack/react-query";
import { BookMarked, ExternalLink, LoaderCircle, X } from "lucide-react";
import { ApiError, readableError } from "../../api/client";
import { itemContextQuery } from "../../api/queries";
import { chunkLocation, documentContentUrl } from "./documents";

/** 右侧"出处"面板：被引用的那段原文与前后文；文档可以打开原文（PDF 跳到对应页）。 */
export function CitationPanel({ itemId, onClose }: { itemId: string; onClose: () => void }) {
  const context = useQuery(itemContextQuery(itemId));
  const target = context.data?.items.find((item) => item.id === context.data?.target_id);
  const document = context.data?.document ?? null;
  return (
    <aside className="flex w-[28rem] max-w-[50%] shrink-0 flex-col border-l border-border bg-card/60">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <BookMarked className="size-4 text-warning" />
        <span className="font-medium">出处</span>
        <button
          aria-label="收起出处面板"
          className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          onClick={onClose}
        >
          <X className="size-4" />
        </button>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4 text-sm">
        {context.isPending && (
          <p className="flex items-center gap-2 text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" />
            加载中…
          </p>
        )}
        {context.isError && (
          <p
            className={
              context.error instanceof ApiError && context.error.status === 404
                ? "text-muted-foreground"
                : "text-danger"
            }
          >
            {context.error instanceof ApiError && context.error.status === 404
              ? "这段内容已不在知识库里（所在的文档或记忆可能已被删除）"
              : `加载失败：${readableError(context.error)}`}
          </p>
        )}
        {target && (
          <>
            <div>
              <p className="font-medium">
                {target.kind === "memory" ? "记忆" : `《${target.document_title ?? "文档"}》`}
              </p>
              {chunkLocation(target) && (
                <p className="text-xs text-muted-foreground">{chunkLocation(target)}</p>
              )}
            </div>
            {document && (
              <a
                href={documentContentUrl(document.id, target.page)}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <ExternalLink className="size-3" />
                打开原文
              </a>
            )}
            <ol className="space-y-2">
              {context.data?.items.map((item) => (
                <li
                  key={item.id}
                  className={`rounded-md px-3 py-2 whitespace-pre-wrap ${
                    item.id === target.id
                      ? "border-l-2 border-warning bg-accent text-foreground"
                      : "text-muted-foreground"
                  }`}
                >
                  {item.content}
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </aside>
  );
}
