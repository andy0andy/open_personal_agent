import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, Plus, Search, TriangleAlert, X } from "lucide-react";
import { useState, type Dispatch, type SetStateAction } from "react";
import { api, readableError } from "../../api/client";
import { knowledgeQuery, pinnedKnowledgeQuery, refreshKnowledge } from "../../api/queries";
import { isImeComposing } from "../../components/ime";
import { PageHeader } from "../../components/ui/PageHeader";
import { DocumentList } from "./DocumentList";
import {
  MAX_LIMIT,
  PAGE_SIZE,
  defaultFilter,
  knowledgeSearchParams,
  listView,
  loadMore,
  parseTags,
  pinnedNotice,
  SUSPICIOUS_PAGE,
  viewLabel,
  type KnowledgeFilter,
  type KnowledgeView,
} from "./filters";
import { ChunkCard, KnowledgeItemCard } from "./KnowledgeItemCard";

const VIEWS: KnowledgeView[] = ["memory", "pinned", "suspicious", "documents"];
// 数可疑的记忆（页签上的数量）：可疑的不会带进对话，要让人看得到有几条
const SUSPICIOUS_COUNT = knowledgeSearchParams({
  ...defaultFilter,
  view: "suspicious",
  limit: SUSPICIOUS_PAGE,
});

/**
 * 知识库页（设计文档 8.4）：记忆的查看、搜索、手动添加、修改、删除与常驻；
 * 文档的上传、处理进度、重新处理、删除，以及在文档里搜索。
 */
export function KnowledgePage() {
  const [filter, setFilter] = useState<KnowledgeFilter>(defaultFilter);
  const [searchText, setSearchText] = useState("");
  // 文档视图不搜索时显示文档列表，不必拉片段
  const showDocuments = filter.view === "documents" && !filter.query.trim();
  const flagged = useQuery(knowledgeQuery(SUSPICIOUS_COUNT)).data?.length ?? 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="知识库" subtitle="智能体记住的关于你的信息，以及你上传的文档" />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-5 px-6 py-5">
          <p className="text-sm text-muted-foreground">
            智能体记住的关于你的信息：常驻信息（个人画像）每次对话都会带上，其余的在相关时自动想起。
            对话中说"记住……"，或每次对话结束后自动整理，都会记到这里。上传的文档在"文档"里，
            智能体回答时会检索它们并注明出处。
          </p>
          <PinnedSection />
          {filter.view !== "documents" && <AddForm />}
          <div className="flex flex-wrap items-center gap-3">
            <div
              role="radiogroup"
              aria-label="视图"
              className="flex rounded-lg border border-border bg-card p-0.5"
            >
              {VIEWS.map((value) => (
                <button
                  key={value}
                  role="radio"
                  aria-checked={filter.view === value}
                  onClick={() =>
                    setFilter((current) => ({ ...current, view: value, limit: PAGE_SIZE }))
                  }
                  className={`rounded-md px-3 py-1 text-sm transition-colors ${
                    filter.view === value
                      ? "bg-accent text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {viewLabel(value, flagged)}
                </button>
              ))}
            </div>
            <label className="flex min-w-48 flex-1 items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-1.5 text-sm focus-within:border-ring">
              <Search className="size-3.5 text-muted-foreground" />
              <input
                aria-label="搜索"
                placeholder={
                  filter.view === "documents"
                    ? "在文档里搜索（按意思或关键词），回车开始"
                    : "搜索（按意思或关键词），回车开始"
                }
                value={searchText}
                onChange={(event) => {
                  setSearchText(event.target.value);
                  // 清空输入框即回到全部列表
                  if (!event.target.value.trim())
                    setFilter((current) => ({ ...current, query: "" }));
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !isImeComposing(event.nativeEvent)) {
                    setFilter((current) => ({ ...current, query: searchText }));
                  }
                }}
                className="min-w-0 flex-1 bg-transparent outline-none"
              />
            </label>
            {filter.tag && (
              <button
                className="flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs hover:text-foreground"
                title="不再按标签筛选"
                onClick={() => setFilter((current) => ({ ...current, tag: null }))}
              >
                #{filter.tag}
                <X className="size-3" />
              </button>
            )}
          </div>
          {filter.query.trim() && (
            <p className="text-xs text-muted-foreground">
              按与「{filter.query.trim()}」的相关程度排列
            </p>
          )}
          {showDocuments ? <DocumentList /> : <ItemList filter={filter} onFilter={setFilter} />}
        </div>
      </div>
    </div>
  );
}

/** 常驻信息（个人画像）：条数、用量与上限；超过上限时提示（设计 2026-10-23 6.6）。 */
function PinnedSection() {
  const pinned = useQuery(pinnedKnowledgeQuery);
  const notice = pinned.data ? pinnedNotice(pinned.data) : null;
  return (
    <section className="rounded-lg border border-border bg-card px-4 py-3 text-sm">
      <p>
        常驻信息
        {pinned.data && (
          <span className="ml-2 text-muted-foreground">
            {pinned.data.items.length} 条，约 {pinned.data.total_tokens} / {pinned.data.token_limit}{" "}
            token
          </span>
        )}
      </p>
      {notice && (
        <p className="mt-1.5 flex items-start gap-1.5 text-warning">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
          {notice}
        </p>
      )}
    </section>
  );
}

/** 条目列表：加载中、出错、没有、列表本身，以及"加载更多"。 */
function ItemList({
  filter,
  onFilter,
}: {
  filter: KnowledgeFilter;
  onFilter: Dispatch<SetStateAction<KnowledgeFilter>>;
}) {
  const items = useQuery(knowledgeQuery(knowledgeSearchParams(filter)));
  const list = listView(items, filter);
  const more = list.kind === "items" ? loadMore(list.items.length, filter.limit) : "none";
  return (
    <>
      {list.kind === "loading" && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" />
          加载中…
        </p>
      )}
      {list.kind === "error" && (
        <p className="text-sm text-danger">加载失败：{readableError(items.error)}</p>
      )}
      {list.kind === "empty" && <p className="text-sm text-muted-foreground">{list.text}</p>}
      {list.kind === "items" && (
        <ul className="space-y-2">
          {list.items.map((item) =>
            item.kind === "document_chunk" ? (
              <ChunkCard key={item.id} item={item} />
            ) : (
              <KnowledgeItemCard
                key={item.id}
                item={item}
                onTag={(tag) => onFilter((current) => ({ ...current, tag }))}
              />
            ),
          )}
        </ul>
      )}
      {more === "capped" && (
        <p className="text-center text-xs text-muted-foreground">
          最多显示 {MAX_LIMIT} 条：更早的请用搜索或标签查找
        </p>
      )}
      {more === "more" && (
        <button
          className="w-full rounded-lg border border-border py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
          onClick={() =>
            onFilter((current) => ({
              ...current,
              limit: Math.min(current.limit + PAGE_SIZE, MAX_LIMIT),
            }))
          }
        >
          加载更多
        </button>
      )}
    </>
  );
}

/** 手动添加一条记忆。 */
function AddForm() {
  const queryClient = useQueryClient();
  const [content, setContent] = useState("");
  const [tags, setTags] = useState("");
  const [pinned, setPinned] = useState(false);
  const add = useMutation({
    mutationFn: api.addKnowledge,
    onSuccess: async () => {
      setContent("");
      setTags("");
      setPinned(false);
      await refreshKnowledge(queryClient);
    },
  });
  return (
    <form
      className="space-y-2 rounded-lg border border-border bg-card p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (content.trim()) add.mutate({ content, tags: parseTags(tags), pinned });
      }}
    >
      <textarea
        aria-label="要记住的信息"
        placeholder="写一条要记住的信息，如：我对花生过敏"
        rows={2}
        value={content}
        onChange={(event) => setContent(event.target.value)}
        className="w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus:border-ring"
      />
      <div className="flex flex-wrap items-center gap-3">
        <input
          aria-label="标签"
          placeholder="标签（用逗号分隔，可不填）"
          value={tags}
          onChange={(event) => setTags(event.target.value)}
          className="min-w-40 flex-1 rounded-md border border-border bg-background px-2 py-1 text-sm outline-none focus:border-ring"
        />
        <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={pinned}
            onChange={(event) => setPinned(event.target.checked)}
          />
          常驻（每次对话都带上）
        </label>
        <button
          type="submit"
          disabled={!content.trim() || add.isPending}
          className="flex items-center gap-1 rounded-md bg-primary px-3 py-1 text-sm text-primary-foreground disabled:opacity-50"
        >
          <Plus className="size-3.5" />
          添加
        </button>
      </div>
      {add.isError && <p className="text-xs text-danger">添加失败：{readableError(add.error)}</p>}
    </form>
  );
}
