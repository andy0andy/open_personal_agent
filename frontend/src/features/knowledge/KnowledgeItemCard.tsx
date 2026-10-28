import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FileText, Pencil, Pin, PinOff, ShieldAlert, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, readableError } from "../../api/client";
import { refreshKnowledge } from "../../api/queries";
import type { KnowledgeItem, KnowledgeUpdate } from "../../api/types";
import { chunkLocation, documentContentUrl } from "./documents";
import { parseTags, sourceLabel } from "./filters";

const ICON_BUTTON = "rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground";

/** 文档片段（在文档里搜索的结果）：只读，显示所属文档与位置，可打开原文。 */
export function ChunkCard({ item }: { item: KnowledgeItem }) {
  const location = chunkLocation(item);
  return (
    <li className="rounded-lg border border-border bg-card px-3 py-2.5">
      <p className="text-sm whitespace-pre-wrap">{item.content}</p>
      <div className="mt-1.5 flex items-center gap-2 text-xs text-muted-foreground">
        <FileText className="size-3.5 shrink-0" />
        <span className="truncate">
          《{item.document_title ?? "文档"}》{location && ` ${location}`}
        </span>
        {item.document_id && (
          <a
            href={documentContentUrl(item.document_id, item.page)}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto flex shrink-0 items-center gap-1 hover:text-foreground"
          >
            <ExternalLink className="size-3" />
            打开原文
          </a>
        )}
      </div>
    </li>
  );
}

/** 一条知识：查看、改内容与标签、设或取消常驻、删除（删除要再点一次确认）。 */
export function KnowledgeItemCard({
  item,
  onTag,
}: {
  item: KnowledgeItem;
  onTag: (tag: string) => void;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const refresh = () => refreshKnowledge(queryClient);
  const update = useMutation({
    mutationFn: (body: KnowledgeUpdate) => api.updateKnowledge(item.id, body),
    onSuccess: async () => {
      setEditing(false);
      await refresh();
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteKnowledge(item.id),
    onSuccess: refresh,
  });
  const error = update.error ?? remove.error;

  if (editing) {
    return (
      <li className="rounded-lg border border-ring bg-card p-3">
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            update.mutate({
              content: String(form.get("content")),
              tags: parseTags(String(form.get("tags"))),
            });
          }}
        >
          <textarea
            name="content"
            aria-label="内容"
            autoFocus
            required
            rows={3}
            defaultValue={item.content}
            className="w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus:border-ring"
          />
          <input
            name="tags"
            aria-label="标签"
            placeholder="标签（用逗号分隔）"
            defaultValue={item.tags.join("，")}
            className="w-full rounded-md border border-border bg-background px-2 py-1 text-sm outline-none focus:border-ring"
          />
          {error && <p className="text-xs text-danger">保存失败：{readableError(error)}</p>}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="rounded-md border border-border px-3 py-1 text-sm hover:bg-muted"
              onClick={() => {
                setEditing(false);
                update.reset();
              }}
            >
              取消
            </button>
            <button
              type="submit"
              disabled={update.isPending}
              className="rounded-md bg-primary px-3 py-1 text-sm text-primary-foreground disabled:opacity-50"
            >
              保存
            </button>
          </div>
        </form>
      </li>
    );
  }

  return (
    <li className="group rounded-lg border border-border bg-card px-3 py-2.5">
      <div className="flex items-start gap-3">
        <p className="min-w-0 flex-1 text-sm whitespace-pre-wrap">{item.content}</p>
        <div className="flex shrink-0 items-center gap-0.5">
          <button
            className={item.pinned ? `${ICON_BUTTON} text-warning` : ICON_BUTTON}
            title={item.pinned ? "取消常驻" : "设为常驻（每次对话都带上）"}
            aria-label={item.pinned ? "取消常驻" : "设为常驻"}
            disabled={update.isPending}
            onClick={() => update.mutate({ pinned: !item.pinned })}
          >
            {item.pinned ? <PinOff className="size-3.5" /> : <Pin className="size-3.5" />}
          </button>
          <button
            className={ICON_BUTTON}
            title="修改"
            aria-label="修改"
            onClick={() => setEditing(true)}
          >
            <Pencil className="size-3.5" />
          </button>
          <button
            className={ICON_BUTTON}
            title="删除"
            aria-label="删除"
            onClick={() => setConfirmingDelete(true)}
          >
            <Trash2 className="size-3.5" />
          </button>
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {item.pinned && (
          <span className="flex items-center gap-1 text-warning">
            <Pin className="size-3" />
            常驻
          </span>
        )}
        {item.tags.map((tag) => (
          <button
            key={tag}
            className="rounded bg-muted px-1.5 py-0.5 hover:text-foreground"
            title={`只看标签「${tag}」`}
            onClick={() => onTag(tag)}
          >
            #{tag}
          </button>
        ))}
        <span>{sourceLabel(item.source)}</span>
        <span>{new Date(item.created_at).toLocaleDateString("zh-CN")}</span>
      </div>
      {item.suspicious && !item.trusted && (
        // 可疑检查（设计 2026-10-23 6.6）：像是写给智能体的指令；确认前不进提示词、不进检索
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-warning/40 bg-warning/10 px-2.5 py-1.5 text-xs">
          <ShieldAlert className="size-3.5 shrink-0 text-warning" />
          <span className="min-w-0 flex-1">
            可疑：内容像是“{item.suspicious}”。确认无害前不会带进对话，也检索不到
          </span>
          <button
            className="rounded-md border border-border bg-card px-2 py-0.5 hover:bg-muted disabled:opacity-50"
            disabled={update.isPending}
            onClick={() => update.mutate({ trusted: true })}
          >
            确认无害
          </button>
        </div>
      )}
      {confirmingDelete && (
        <div className="mt-2 flex items-center gap-2 text-sm">
          <span className="text-danger">删除这条？删除后无法恢复。</span>
          <button
            className="rounded-md bg-danger px-2.5 py-0.5 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-50"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
          >
            删除
          </button>
          <button
            className="rounded-md border border-border px-2.5 py-0.5 text-sm hover:bg-muted"
            onClick={() => {
              setConfirmingDelete(false);
              remove.reset();
            }}
          >
            取消
          </button>
        </div>
      )}
      {error && !editing && (
        <p className="mt-1.5 text-xs text-danger">操作失败：{readableError(error)}</p>
      )}
    </li>
  );
}
