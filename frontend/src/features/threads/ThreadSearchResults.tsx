import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { threadSearchQuery } from "../../api/queries";
import type { Thread } from "../../api/types";
import { SEARCH_DELAY_MS, extraTitleMatches, highlightParts, hitLink, queryWords } from "./search";

/**
 * 搜索框有字时列表下方的结果（设计 2026-10-23 6.1）：停顿后查服务器，补上本地即时过滤里没有的
 * 标题匹配（如已归档的会话），再列出"内容里提到"的那几轮（命中词加粗）。
 */
export function ThreadSearchResults({ query, shown }: { query: string; shown: Thread[] }) {
  const navigate = useNavigate();
  const typed = query.trim();
  const [settled, setSettled] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setSettled(typed), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [typed]);
  const search = useQuery({ ...threadSearchQuery(settled), enabled: settled !== "" });
  if (settled === "" || settled !== typed) return null; // 还在打字
  if (search.isError) return <p className="px-2 text-xs text-danger">搜索失败，请稍后再试</p>;
  if (!search.data) return <p className="px-2 text-xs text-muted-foreground">正在查内容…</p>;
  const extras = extraTitleMatches(shown, search.data.titles);
  return (
    <div className="space-y-1">
      {extras.map((thread) => (
        <button
          key={thread.id}
          type="button"
          className="block w-full truncate rounded-lg px-2.5 py-1.5 text-left text-[13px] hover:bg-muted"
          onClick={() => navigate(`/chat/${thread.id}`)}
        >
          {thread.title || "新会话"}
        </button>
      ))}
      <p className="px-2 pt-2 text-xs font-medium text-muted-foreground">内容里提到</p>
      {search.data.hits.length === 0 ? (
        <p className="px-2 text-xs text-muted-foreground">内容里没有提到“{settled}”</p>
      ) : (
        search.data.hits.map((hit) => (
          <button
            key={hit.run_id}
            type="button"
            className="block w-full rounded-lg px-2.5 py-1.5 text-left hover:bg-muted"
            onClick={() => navigate(hitLink(hit))}
          >
            <span className="block truncate text-[13px]">
              {hit.title || "新会话"}
              <span className="ml-1.5 text-xs text-muted-foreground">第 {hit.turn} 轮</span>
            </span>
            <span className="line-clamp-2 text-xs text-muted-foreground">
              {highlightParts(
                hit.snippet,
                hit.terms.length > 0 ? hit.terms : queryWords(settled),
              ).map((part, index) =>
                part.hit ? (
                  <mark key={index} className="bg-transparent font-semibold text-foreground">
                    {part.text}
                  </mark>
                ) : (
                  <span key={index}>{part.text}</span>
                ),
              )}
            </span>
          </button>
        ))
      )}
    </div>
  );
}
