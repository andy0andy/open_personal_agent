import {
  ActionBarPrimitive,
  MessagePrimitive,
  groupPartByType,
  useAuiState,
  type DataMessagePartComponent,
  type ToolCallMessagePartComponent,
} from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import type { Components } from "react-markdown";
import {
  BookmarkCheck,
  BookMarked,
  Bot,
  Brain,
  Check,
  ChevronRight,
  CircleStop,
  Clock,
  Copy,
  Download,
  ExternalLink,
  FileText,
  Gauge,
  Hourglass,
  ListTodo,
  LoaderCircle,
  MessagesSquare,
  Paperclip,
  RotateCcw,
  ShieldQuestion,
  Timer,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import { useContext, useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import remarkGfm from "remark-gfm";
import "katex/dist/katex.min.css";
import { downloadWithFreshSession, reloadImageOnce } from "../../api/session";
import type { InterruptedUsage, TodoItem } from "../../api/types";
import type { ChatItem } from "../../features/chat/reducer";
import { formatDuration, formatElapsed, formatTokens } from "../../features/usage/format";
import {
  SUBAGENT_TOOL,
  itemState,
  stepState,
  type FileCardData,
  type InterjectionData,
  type MemoryNoteData,
  type RetriedData,
  type ThinkingData,
  type StepState,
  type SubagentArtifact,
  type TurnUsage,
  type UserAttachment,
} from "./adapter";
import { citationTarget, linkKind } from "../../features/knowledge/citations";
import {
  conversationPath,
  conversationTarget,
  type ConversationTarget,
} from "../../features/chat/conversationLinks";
import { ApprovalPart } from "./approval";
import { OpenCitationContext } from "./citationActions";
import { OpenFileContext } from "./fileActions";
import { CodeBlock, CodeHeader } from "./code";
import { formatSize } from "../format";
import { MATH_REHYPE_PLUGINS, MATH_REMARK_PLUGINS, normalizeMath } from "./math";
import { ErrorCard } from "./errorCard";
import { MessageRunningContext } from "./messageContext";
import { TodoList } from "./TodoBar";
import { todoProgress } from "../../features/chat/todos";
import { ToolGroup, ToolLine } from "./toolLine";
import { toolLabel } from "./tools";

/**
 * 回答里的链接：知识库出处（#kb-<条目 ID>）显示成出处按钮，点开右侧"出处"面板；
 * 其他链接在新标签页打开。
 */
const MarkdownLink: Components["a"] = ({ href, children }) => {
  const openCitation = useContext(OpenCitationContext);
  const conversation = conversationTarget(href);
  if (conversation) return <ConversationLink target={conversation}>{children}</ConversationLink>;
  const target = citationTarget(href);
  // 格式不对的出处、会话链接按普通文字显示（不在新标签页打开应用）
  if (linkKind(href) === "broken-citation" || href?.startsWith("#conv-")) {
    return <span>{children}</span>;
  }
  if (target === null) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  }
  return (
    <button
      type="button"
      title="查看出处"
      className="mx-0.5 inline-flex items-center gap-0.5 rounded bg-muted px-1 align-baseline text-xs text-foreground hover:bg-accent"
      onClick={() => openCitation(target)}
    >
      <BookMarked className="size-3 shrink-0 text-warning" />
      {children}
    </button>
  );
};

/** 以前的对话（设计 2026-10-23 6.1）：在本页打开那个会话并滚到那一轮。 */
function ConversationLink({
  target,
  children,
}: {
  target: ConversationTarget;
  children: ReactNode;
}) {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      title="打开这段对话"
      className="mx-0.5 inline-flex items-center gap-0.5 rounded bg-muted px-1 align-baseline text-xs text-foreground hover:bg-accent"
      onClick={() => navigate(conversationPath(target))}
    >
      <MessagesSquare className="size-3 shrink-0 text-info" />
      {children}
    </button>
  );
}

const MARKDOWN_COMPONENTS = { a: MarkdownLink, SyntaxHighlighter: CodeBlock, CodeHeader };
const REMARK_PLUGINS = [remarkGfm, ...MATH_REMARK_PLUGINS];

/** 回答正文：GitHub 风格 Markdown、代码高亮与数学公式（D19）。 */
const MarkdownText = () => (
  <MarkdownTextPrimitive
    remarkPlugins={REMARK_PLUGINS}
    rehypePlugins={MATH_REHYPE_PLUGINS}
    preprocess={normalizeMath}
    components={MARKDOWN_COMPONENTS}
    className="markdown"
    // 关闭 assistant-ui 的逐字动画（smooth）：运行中刷新页面时，已有正文的回答在运行结束前一直
    // 显示为空白（0.15.28 实测）。回答本身就是逐字推送的，关掉后观感相近
    smooth={false}
    // 逐字输出时每来一段都要重新解析、重新渲染全部公式（公式多时较慢）：降为低优先级，
    // 界面忙时跳过中间几次，打字和滚动不受影响；最终的全文总会渲染
    defer
  />
);

const STEP_LABELS: Record<StepState, { icon: ReactNode; text: string }> = {
  running: { icon: <LoaderCircle className="size-3.5 animate-spin" />, text: "运行中" },
  success: { icon: <Check className="size-3.5 text-success" />, text: "完成" },
  error: { icon: <TriangleAlert className="size-3.5 text-danger" />, text: "出错" },
  interrupted: { icon: <CircleStop className="size-3.5" />, text: "已中断" },
  waiting: { icon: <ShieldQuestion className="size-3.5 text-warning" />, text: "等待审批" },
  paused: { icon: <Hourglass className="size-3.5" />, text: "等待中" },
};

function StatusLabel({ state }: { state: StepState }) {
  const { icon, text } = STEP_LABELS[state];
  return (
    <span className="ml-auto flex shrink-0 items-center gap-1 text-xs">
      {icon}
      {text}
    </span>
  );
}

/** 子智能体内部步骤：回答原文、思考、工具调用，嵌套的子智能体递归显示。active：子智能体仍在运行。 */
function NestedItems({
  items,
  active,
  paused = false,
}: {
  items: ChatItem[];
  active: boolean;
  paused?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      {items.map((item) => {
        switch (item.kind) {
          case "assistant":
            return (
              <p key={item.id} className="whitespace-pre-wrap">
                {item.text}
              </p>
            );
          case "thinking":
            return (
              <p key={item.id} className="whitespace-pre-wrap text-muted-foreground italic">
                {item.text}
              </p>
            );
          case "tool": {
            const { verb, detail } = toolLabel(item.name, item.args);
            return (
              <p key={item.id} className="flex items-center gap-2 text-muted-foreground">
                <Wrench className="size-3 shrink-0" aria-hidden="true" />
                <span className="shrink-0">{verb}</span>
                {detail && (
                  <span className="min-w-0 truncate font-mono text-foreground">{detail}</span>
                )}
                <StatusLabel state={itemState(item.status, active, paused)} />
              </p>
            );
          }
          case "subagent":
            return (
              <div key={item.id} className="border-l-2 border-border pl-3">
                <p className="text-muted-foreground">
                  {item.name}：{item.description}
                </p>
                <NestedItems
                  items={item.items}
                  active={active && item.status === "running"}
                  paused={paused}
                />
              </div>
            );
          default:
            return null;
        }
      })}
    </div>
  );
}

/** 子智能体卡片（设计文档 13.1：工具调用片段里的嵌套内容）：默认折叠，展开看它的每一步。 */
export const SubagentCard: ToolCallMessagePartComponent = ({
  artifact,
  result,
  isError,
  status,
}) => {
  const subagent = artifact as SubagentArtifact;
  const state = stepState(result, isError, status, false, subagent.paused ?? false);
  return (
    <details className="group my-2 rounded-lg border border-border bg-card text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-muted-foreground">
        <ChevronRight className="size-3.5 shrink-0 transition-transform group-open:rotate-90" />
        <Bot className="size-3.5 shrink-0 text-warning" />
        <span className="shrink-0 font-mono text-foreground">{subagent.name}</span>
        <span className="truncate">{subagent.description}</span>
        <StatusLabel state={state} />
      </summary>
      <div className="space-y-3 border-t border-border px-3 py-2 text-xs">
        <NestedItems
          items={subagent.items}
          active={state === "running"}
          paused={state === "paused"}
        />
        {result !== undefined && (
          <div className="border-t border-border pt-2">
            <p className="mb-1 text-muted-foreground">交回的结果</p>
            <p className="whitespace-pre-wrap">{String(result)}</p>
          </div>
        )}
      </div>
    </details>
  );
};

/** 思考的标题：进行中"思考中…"；有用时"思考了 N 秒"；旧记录、被打断的算不出用时，写"思考过程"。 */
function thinkingTitle({ seconds, running }: ThinkingData): string {
  if (running) return "思考中…";
  if (seconds === null) return "思考过程";
  if (seconds < 1) return "思考了不到 1 秒";
  return `思考了 ${seconds < 60 ? `${seconds} 秒` : formatDuration(seconds * 1000)}`;
}

/** 思考（设计 2026-10-22 3.4）：一行次要色小字，点开看内容。 */
export const ThinkingPart: DataMessagePartComponent = ({ data }) => {
  const thinking = data as ThinkingData;
  return (
    <details className="group/think my-2 text-[13px] text-muted-foreground">
      <summary className="flex cursor-pointer list-none items-center gap-2 transition-colors hover:text-foreground">
        <ChevronRight
          aria-hidden="true"
          className="size-3.5 shrink-0 transition-transform group-open/think:rotate-90"
        />
        <Brain aria-hidden="true" className="size-3.5 shrink-0" />
        {thinkingTitle(thinking)}
      </summary>
      <p className="mt-2 ml-1.5 border-l border-border pl-4 whitespace-pre-wrap">{thinking.text}</p>
    </details>
  );
};

/** 这一轮是否还在进行：回答在输出，或在等你审批（结束后没做完的待办写"未完成"）。 */
function useRoundActive(): boolean {
  return useAuiState(
    ({ message }) =>
      message.status?.type === "running" ||
      message.parts.some(
        (part) =>
          part.type === "data" &&
          part.name === "approval" &&
          ["pending", "submitting"].includes((part.data as { status?: string }).status ?? ""),
      ),
  );
}

/** 对话流里的待办（设计 2026-10-22 3.7）：一行"待办 2/4"，点开看清单；进行中的进度在输入框上方。 */
export const TodosPart: DataMessagePartComponent = ({ data }) => {
  const todos = data as TodoItem[];
  const active = useRoundActive();
  const { done, total } = todoProgress(todos);
  return (
    <details className="group/todos my-2 text-[13px] text-muted-foreground">
      <summary className="flex cursor-pointer list-none items-center gap-2 transition-colors hover:text-foreground">
        <ChevronRight
          aria-hidden="true"
          className="size-3.5 shrink-0 transition-transform group-open/todos:rotate-90"
        />
        <ListTodo aria-hidden="true" className="size-3.5 shrink-0" />
        <span className="tabular-nums">{`待办 ${done}/${total}`}</span>
      </summary>
      <div className="mt-2 ml-1.5 border-l border-border pl-4">
        <TodoList todos={todos} active={active} />
      </div>
    </details>
  );
};

const LINK_BUTTON = "rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground";

/**
 * 产物文件卡片：图片直接显示；其他文件显示名称与大小。
 * 点图片或文件名在右侧文件面板里预览；也可以在新标签页打开或下载。
 */
export const FilePart: DataMessagePartComponent = ({ data }) => {
  const file = data as FileCardData;
  const openFile = useContext(OpenFileContext);
  return (
    <div className="my-2 max-w-md overflow-hidden rounded-lg border border-border bg-card text-sm">
      {file.mediaType.startsWith("image/") && (
        <button
          className="block w-full"
          onClick={() => openFile(file.fileId)}
          title="在文件面板里预览"
        >
          <img
            src={file.url}
            alt={file.name}
            loading="lazy"
            className="max-h-80 w-full bg-muted object-contain"
            onError={(event) => void reloadImageOnce(event.currentTarget)}
          />
        </button>
      )}
      <div className="flex items-center gap-2 px-3 py-2">
        <FileText className="size-4 shrink-0 text-muted-foreground" />
        <button
          className="truncate hover:underline"
          title={`${file.path}（在文件面板里预览）`}
          onClick={() => openFile(file.fileId)}
        >
          {file.name}
        </button>
        <span className="shrink-0 text-xs text-muted-foreground">{formatSize(file.size)}</span>
        <span className="ml-auto flex shrink-0 gap-1">
          <a
            href={file.url}
            target="_blank"
            rel="noopener noreferrer"
            className={LINK_BUTTON}
            aria-label="打开"
            title="打开"
          >
            <ExternalLink className="size-3.5" />
          </a>
          <a
            href={file.downloadUrl}
            download={file.name}
            className={LINK_BUTTON}
            aria-label="下载"
            title="下载"
            onClick={(event) => {
              event.preventDefault(); // 先换一次令牌再下载（后端重启后 Cookie 里的令牌旧了）
              void downloadWithFreshSession(file.downloadUrl, file.name);
            }}
          >
            <Download className="size-3.5" />
          </a>
        </span>
      </div>
    </div>
  );
};

/** 智能体记下了一条记忆（设计文档 8.2）：可在知识库页查看、修改或删除。 */
export const MemoryPart: DataMessagePartComponent = ({ data }) => {
  const memory = data as MemoryNoteData;
  if (memory.suspicious) {
    return (
      <p className="my-1.5 flex items-start gap-1.5 text-xs text-warning">
        <TriangleAlert className="mt-px size-3.5 shrink-0" />
        <span>
          已记住，但像是“{memory.suspicious}”，标为可疑：在知识库页确认前不会用上。内容：
          {memory.content}
        </span>
      </p>
    );
  }
  return (
    <p className="my-1.5 flex items-start gap-1.5 text-xs text-muted-foreground">
      <BookmarkCheck className="mt-px size-3.5 shrink-0 text-success" />
      <span>
        已记住{memory.pinned ? "（常驻）" : ""}：{memory.content}
      </span>
    </p>
  );
};

/** 运行中插的话（设计 2026-10-23 6.3）：像用户消息一样靠右；还没送达时标"已排队"。 */
export const InterjectionPart: DataMessagePartComponent = ({ data }) => {
  const note = data as InterjectionData;
  return (
    <div
      className="my-2 flex flex-col items-end"
      data-interjection={note.undelivered ? "undelivered" : note.queued ? "queued" : "sent"}
    >
      <div className="max-w-[80%] rounded-xl border border-border bg-accent px-3.5 py-2 whitespace-pre-wrap text-foreground">
        {note.text}
      </div>
      <span className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
        {note.queued && <Clock className="size-3" />}
        {note.undelivered
          ? "没送达：这一轮结束前没来得及交给智能体"
          : note.queued
            ? "已排队：智能体下一步开始前送达"
            : "运行中插话"}
      </span>
    </div>
  );
};

/** 重试过的失败轮收成的一行（D26）：第几次失败、原因。 */
export const RetriedPart: DataMessagePartComponent = ({ data }) => {
  const retried = data as RetriedData;
  return (
    <p className="my-1.5 flex items-start gap-1.5 text-xs text-muted-foreground">
      <RotateCcw className="mt-px size-3.5 shrink-0" />
      <span className="min-w-0 break-words">
        第 {retried.attempt} 次失败：{retried.text}（已重试）
      </span>
    </p>
  );
};

/** 运行中的已用时间，每秒刷新。 */
function ElapsedTime({ startedAt, pausedMs }: { startedAt: string; pausedMs: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return <>已用 {formatElapsed(Math.max(0, now - Date.parse(startedAt) - pausedMs))}</>;
}

/** 本轮耗时：结束后显示总耗时；运行中显示实时计时；没有正常结束（如服务崩溃）则不显示。 */
function TurnDuration({ timing, running }: { timing: TurnTiming; running: boolean }) {
  if (!timing.finishedAt && !running) return null;
  return (
    <span className="flex items-center gap-1 font-mono">
      <Timer className="size-3.5" />
      {timing.finishedAt ? (
        <>
          耗时{" "}
          {formatDuration(
            Math.max(
              0,
              Date.parse(timing.finishedAt) - Date.parse(timing.startedAt) - (timing.pausedMs ?? 0),
            ),
          )}
        </>
      ) : (
        <ElapsedTime startedAt={timing.startedAt} pausedMs={timing.pausedMs ?? 0} />
      )}
    </span>
  );
}

interface TurnTiming {
  startedAt: string;
  finishedAt?: string;
  pausedMs?: number; // 等待审批的时间，不算进耗时
}

/**
 * 回答下方的一行：耗时、已停止、被中断调用的估算、本轮用量（可展开明细），末尾是复制按钮。
 * 复制按钮一直显示（不用鼠标移上去才出现），只在回答进行中隐藏。
 */
function AssistantFooter() {
  const custom = useAuiState(({ message }) => message.metadata.custom);
  const running = useAuiState(({ message }) => message.status?.type === "running");
  const usage = custom.usage as TurnUsage | undefined;
  const stopped = custom.stopped === true;
  const interrupted = custom.interruptedUsage as InterruptedUsage | undefined;
  const timing = custom.timing as TurnTiming | undefined;
  // 没有正文（只有报错、或很旧的记录）时不放复制按钮：复制出来是空的
  const hasText = useAuiState(({ message }) =>
    message.content.some((part) => part.type === "text" && part.text.trim() !== ""),
  );
  if (!timing && !stopped && !interrupted && !usage && !hasText) return null;
  return (
    <div className="mt-2 flex flex-wrap items-start gap-3 text-xs text-muted-foreground">
      {timing && <TurnDuration timing={timing} running={running} />}
      {stopped && (
        <span className="flex items-center gap-1">
          <CircleStop className="size-3.5" />
          已停止
        </span>
      )}
      {interrupted && (
        <span
          className="font-mono"
          title="中断后网关不返回用量，这是按发送内容与已输出文字的估算，不计入合计"
        >
          被中断的调用：输入约 {formatTokens(interrupted.input_tokens)} · 输出约{" "}
          {formatTokens(interrupted.output_tokens)}
        </span>
      )}
      {usage && (
        <details className="group">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 font-mono">
            <Gauge className="size-3.5" />
            输入 {formatTokens(usage.input_tokens)} · 输出 {formatTokens(usage.output_tokens)}
          </summary>
          <table className="mt-1 font-mono">
            <tbody>
              {usage.calls.map((call, index) => (
                <tr key={index}>
                  <td className="pr-3">{call.caller}</td>
                  <td className="pr-3">{call.actual_model}</td>
                  <td className="pr-3">
                    {formatTokens(call.input_tokens)} / {formatTokens(call.output_tokens)}
                  </td>
                  <td>{(call.duration_ms / 1000).toFixed(1)}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      {hasText && (
        <ActionBarPrimitive.Root hideWhenRunning className="flex">
          <ActionBarPrimitive.Copy
            className="-my-1 rounded-md p-1 hover:bg-muted hover:text-foreground"
            aria-label="复制"
            title="复制回答"
          >
            <Copy className="size-3.5" />
          </ActionBarPrimitive.Copy>
        </ActionBarPrimitive.Root>
      )}
    </div>
  );
}

/** 用户消息下方的附件标签：点开在文件面板里预览。 */
function UserAttachments() {
  const custom = useAuiState(({ message }) => message.metadata.custom);
  const openFile = useContext(OpenFileContext);
  const attachments = custom.attachments as UserAttachment[] | undefined;
  if (!attachments?.length) return null;
  return (
    <div className="mt-1 flex max-w-[80%] flex-wrap justify-end gap-1">
      {attachments.map((file) => (
        <button
          key={file.fileId}
          className="flex items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-xs hover:bg-muted"
          title="在文件面板里预览"
          onClick={() => openFile(file.fileId)}
        >
          <Paperclip className="size-3.5 text-muted-foreground" />
          <span className="max-w-48 truncate">{file.name}</span>
          <span className="text-muted-foreground">{formatSize(file.size)}</span>
        </button>
      ))}
    </div>
  );
}

/** 用户消息（设计 2026-10-22 3.3）：强调底 + 分隔线色边框 + 正文色文字，右对齐。 */
export const UserMessage = () => (
  <MessagePrimitive.Root className="group flex flex-col items-end">
    <MessageAnchor />
    <div className="max-w-[80%] rounded-xl border border-border bg-accent px-3.5 py-2.5 whitespace-pre-wrap text-foreground">
      <MessagePrimitive.Parts />
    </div>
    <UserAttachments />
    <ActionBarPrimitive.Root className="mt-1 flex gap-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
      <ActionBarPrimitive.Copy
        className="rounded-md p-1 hover:bg-muted hover:text-foreground"
        aria-label="复制"
      >
        <Copy className="size-3.5" />
      </ActionBarPrimitive.Copy>
    </ActionBarPrimitive.Root>
  </MessagePrimitive.Root>
);

/** 用户消息的定位点：会话链接、搜索结果点进来时按它滚到那一轮（id 形如 user-<运行 ID>）。 */
function MessageAnchor() {
  const id = useAuiState(({ message }) => message.id);
  return <span data-message-id={id} aria-hidden="true" />;
}

const DATA_PARTS: Record<string, DataMessagePartComponent> = {
  thinking: ThinkingPart,
  todos: TodosPart,
  file: FilePart,
  memory: MemoryPart,
  interjection: InterjectionPart,
  retried: RetriedPart,
  approval: ApprovalPart,
};

// 相邻的工具调用合成一组（设计 2026-10-22 3.5）；子智能体单独成行，不并入
const GROUP_TOOLS = groupPartByType({
  "tool-call": ["group-tools"],
  [`tool-call:${SUBAGENT_TOOL}`]: [],
});

export const AssistantMessage = () => {
  const running = useAuiState(({ message }) => message.status?.type === "running");
  return (
    <MessagePrimitive.Root className="group relative">
      <MessageRunningContext value={running}>
        <MessagePrimitive.GroupedParts groupBy={GROUP_TOOLS} indicator="never">
          {({ part, children }) => {
            switch (part.type) {
              case "group-tools":
                // 与其他片段（卡片、思考）一样上下留 8px
                return (
                  <div className="my-2">
                    <ToolGroup indices={part.indices}>{children}</ToolGroup>
                  </div>
                );
              case "text":
                return <MarkdownText />;
              case "tool-call":
                return part.toolName === SUBAGENT_TOOL ? (
                  <SubagentCard {...part} />
                ) : (
                  <ToolLine {...part} />
                );
              case "data": {
                const Data = DATA_PARTS[part.name];
                return Data ? <Data {...part} /> : <></>;
              }
              default:
                return <></>;
            }
          }}
        </MessagePrimitive.GroupedParts>
      </MessageRunningContext>
      <ErrorCard />
      <AssistantFooter />
    </MessagePrimitive.Root>
  );
};
