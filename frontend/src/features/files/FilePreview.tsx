import { useQuery } from "@tanstack/react-query";
import { Download, ExternalLink, LoaderCircle } from "lucide-react";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { downloadWithFreshSession, reloadImageOnce } from "../../api/session";
import { fileContentUrl, readableError } from "../../api/client";
import { fileTextQuery, tablePreviewQuery } from "../../api/queries";
import type { WorkspaceFile } from "../../api/types";
import { fileName, formatSize } from "../../components/format";
import { previewKind } from "./kind";

const LINK_BUTTON = "rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground";

/**
 * 按类型预览一个文件（设计文档 9.3）：图片直接显示；CSV / Excel 显示前若干行；PDF 用浏览器阅读器；
 * Markdown 渲染；网页放在隔离的内嵌框里（不执行脚本）；文字原样显示；其他只能下载。
 */
export function FilePreview({ file }: { file: WorkspaceFile }) {
  const name = fileName(file.path);
  // 带上更新时间：同一文件被改写后（地址不变）浏览器不会用旧的缓存
  const src = `${fileContentUrl(file.thread_id, file.id, false)}?v=${encodeURIComponent(file.updated_at)}`;
  const kind = previewKind(file);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 px-4 py-2 text-sm">
        <span className="truncate font-medium" title={file.path}>
          {name}
        </span>
        <span className="shrink-0 text-xs text-muted-foreground">{formatSize(file.size)}</span>
        <span className="ml-auto flex shrink-0 gap-1">
          <a
            href={src}
            target="_blank"
            rel="noopener noreferrer"
            className={LINK_BUTTON}
            title="在新标签页打开"
          >
            <ExternalLink className="size-4" />
          </a>
          <a
            href={fileContentUrl(file.thread_id, file.id, true)}
            download={name}
            className={LINK_BUTTON}
            title="下载"
            onClick={(event) => {
              event.preventDefault(); // 先换一次令牌再下载（后端重启后 Cookie 里的令牌旧了）
              void downloadWithFreshSession(event.currentTarget.href, name);
            }}
          >
            <Download className="size-4" />
          </a>
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-4 pb-4">
        {kind === "image" && (
          <img
            src={src}
            alt={name}
            className="max-w-full rounded-md bg-muted"
            onError={(event) => void reloadImageOnce(event.currentTarget)}
          />
        )}
        {kind === "pdf" && <iframe src={src} title={name} className="h-full w-full rounded-md" />}
        {kind === "html" && (
          // sandbox 不带 allow-scripts：智能体生成的网页里的脚本不执行
          <iframe src={src} title={name} sandbox="" className="h-full w-full rounded-md" />
        )}
        {kind === "table" && <TableView file={file} />}
        {(kind === "markdown" || kind === "text") && (
          <TextView file={file} markdown={kind === "markdown"} />
        )}
        {kind === "none" && (
          <p className="text-sm text-muted-foreground">这种文件不能在页面里预览，请下载后查看。</p>
        )}
      </div>
    </div>
  );
}

function TableView({ file }: { file: WorkspaceFile }) {
  const [sheet, setSheet] = useState<string | null>(null);
  const table = useQuery(tablePreviewQuery(file, sheet));
  if (table.isError) return <p className="text-sm text-danger">{readableError(table.error)}</p>;
  if (!table.data) return <Loading />;
  const [header, ...body] = table.data.rows;
  return (
    <div className="space-y-2 text-sm">
      {table.data.sheets.length > 1 && (
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="工作表">
          {table.data.sheets.map((name) => (
            <button
              key={name}
              role="tab"
              aria-selected={name === table.data.sheet}
              className="rounded-md border border-border px-2 py-0.5 text-xs aria-selected:bg-primary aria-selected:text-primary-foreground"
              onClick={() => setSheet(name)}
            >
              {name}
            </button>
          ))}
        </div>
      )}
      {header ? (
        <table className="w-full border-collapse font-mono text-xs">
          <thead>
            <tr>
              {header.map((cell, index) => (
                <th key={index} className="border border-border bg-muted px-2 py-1 text-left">
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, index) => (
                  <td key={index} className="border border-border px-2 py-1 whitespace-nowrap">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-muted-foreground">这张表是空的。</p>
      )}
      {table.data.truncated && (
        <p className="text-xs text-muted-foreground">
          只显示前 {table.data.rows.length} 行，完整内容请下载查看。
        </p>
      )}
      {table.data.columns_truncated && (
        <p className="text-xs text-muted-foreground">只显示前 50 列，完整内容请下载查看。</p>
      )}
    </div>
  );
}

function TextView({ file, markdown }: { file: WorkspaceFile; markdown: boolean }) {
  const text = useQuery(fileTextQuery(file));
  if (text.isError) return <p className="text-sm text-danger">{readableError(text.error)}</p>;
  if (text.data === undefined) return <Loading />;
  return markdown ? (
    <div className="markdown text-sm">
      <Markdown remarkPlugins={[remarkGfm]}>{text.data}</Markdown>
    </div>
  ) : (
    <pre className="font-mono text-xs whitespace-pre-wrap">{text.data}</pre>
  );
}

function Loading() {
  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <LoaderCircle className="size-4 animate-spin" />
      加载中…
    </p>
  );
}
