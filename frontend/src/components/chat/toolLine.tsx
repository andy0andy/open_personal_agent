import { useAuiState } from "@assistant-ui/react";
import {
  Bookmark,
  BookmarkPlus,
  BookOpen,
  Check,
  ChevronRight,
  CircleStop,
  FilePen,
  FileText,
  FolderSearch,
  History,
  Hourglass,
  ListTodo,
  LoaderCircle,
  Plug,
  ShieldQuestion,
  Terminal,
  TriangleAlert,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import type { DecisionView } from "../../features/chat/approvals";
import { formatDuration } from "../../features/usage/format";
import { Tag } from "../ui/Tag";
import { stepState, type StepState, type ToolArtifact } from "./adapter";
import { parseExecuteOutput, summarizeTools, toolLabel, type ToolKind } from "./tools";

const KIND_ICONS: Record<ToolKind, LucideIcon> = {
  read: FileText,
  find: FolderSearch,
  write: FilePen,
  execute: Terminal,
  knowledge: BookOpen,
  conversations: History,
  memory: BookmarkPlus,
  memory_change: Bookmark,
  todos: ListTodo,
  external: Plug,
  other: Wrench,
};

/** 一次工具调用（assistant-ui 工具片段里用到的几项）。 */
export interface ToolCallView {
  toolName: string;
  args: Readonly<Record<string, unknown>>;
  status: { type: string };
  result?: unknown;
  isError?: boolean;
  artifact?: unknown;
}

/**
 * 用时的起止：从工具真正开始执行算起（设计 2026-10-23 5.7）；旧历史没有这个时间，
 * 就从调用开始算，但等过审批的不算（里面有等你的时间）。还没结束的没有。
 */
function spanOf(artifact: ToolArtifact | undefined): { start: number; end: number } | null {
  const start = artifact?.runningAt ?? (artifact?.waited ? undefined : artifact?.startedAt);
  if (!start || !artifact?.finishedAt) return null;
  return { start: Date.parse(start), end: Date.parse(artifact.finishedAt) };
}

/** 用时：只有顺利结束的才显示。 */
function toolDuration(state: StepState, artifact: ToolArtifact | undefined): string | null {
  const span = state === "success" ? spanOf(artifact) : null;
  return span ? formatDuration(Math.max(0, span.end - span.start)) : null;
}

/** 工具行右侧：运行中、等待审批、出错、已中断写出来；成功只显示用时（不写"完成"）。 */
function ToolStatus({ state, duration }: { state: StepState; duration: string | null }) {
  const content: Record<StepState, ReactNode> = {
    running: (
      <>
        <LoaderCircle className="size-3.5 animate-spin" aria-hidden="true" />
        运行中
      </>
    ),
    waiting: (
      <>
        <ShieldQuestion className="size-3.5 text-warning" aria-hidden="true" />
        等待审批
      </>
    ),
    paused: (
      <>
        <Hourglass className="size-3.5" aria-hidden="true" />
        等待中
      </>
    ),
    error: (
      <span className="flex items-center gap-1 text-danger">
        <TriangleAlert className="size-3.5" aria-hidden="true" />
        出错
      </span>
    ),
    interrupted: (
      <>
        <CircleStop className="size-3.5" aria-hidden="true" />
        已中断
      </>
    ),
    success: duration && <span className="font-mono">{duration}</span>,
  };
  return <span className="ml-auto flex shrink-0 items-center gap-1 text-xs">{content[state]}</span>;
}

const DECISION_STYLES: Record<DecisionView["tone"], { icon: LucideIcon; className: string }> = {
  success: { icon: Check, className: "text-success" },
  danger: { icon: X, className: "text-danger" },
  muted: { icon: CircleStop, className: "text-muted-foreground" },
};

/** 处理过的审批并入工具行（设计 2026-10-22 3.6）：已同意 / 已修改参数后执行 / 已拒绝 / 已回复：… */
function Decision({ decision }: { decision: DecisionView }) {
  const { icon: Icon, className } = DECISION_STYLES[decision.tone];
  return (
    <span className={`flex min-w-0 shrink items-center gap-1 ${className}`}>
      <Icon aria-hidden="true" className="size-3.5 shrink-0" />
      <span className="truncate">{decision.label}</span>
    </span>
  );
}

/** 执行命令展开后：$ 命令 + 退出码徽标 + 输出（去掉末尾的退出码那一行，设计 2026-10-22 3.5）。 */
function ExecuteDetails({
  command,
  output,
  exitCode,
  stderr,
}: {
  command: string;
  output: string | null;
  exitCode: number | null;
  stderr: string;
}) {
  const parsed = output === null ? null : { ...parseExecuteOutput(output), exitCode };
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card font-mono text-[13px]">
      <div className="flex items-start gap-2 px-3 py-2">
        <span aria-hidden="true" className="text-muted-foreground">
          $
        </span>
        <span className="min-w-0 flex-1 break-all whitespace-pre-wrap">{command}</span>
        {parsed?.exitCode != null && (
          <Tag tone={parsed.exitCode === 0 ? "success" : "danger"}>
            <span
              aria-hidden="true"
              className={`size-1.5 rounded-full ${parsed.exitCode === 0 ? "bg-success" : "bg-danger"}`}
            />
            {`退出码 ${parsed.exitCode}`}
          </Tag>
        )}
      </div>
      {parsed?.text && (
        <pre className="max-h-80 overflow-auto border-t border-border px-3 py-2.5 text-xs leading-relaxed whitespace-pre-wrap text-muted-foreground">
          {parsed.text}
        </pre>
      )}
      {stderr && (
        <div className="border-t border-border">
          <p className="px-3 pt-2 font-sans text-xs text-danger">错误输出</p>
          <pre className="max-h-60 overflow-auto px-3 pt-1 pb-2.5 text-xs leading-relaxed whitespace-pre-wrap text-muted-foreground">
            {stderr}
          </pre>
        </div>
      )}
    </div>
  );
}

// 摘要已经说清楚的工具不再显示参数（读取、查找、检索、记忆、待办）
const SHOW_ARGS: ReadonlySet<ToolKind> = new Set(["write", "external", "other"]);

function OtherDetails({
  kind,
  args,
  output,
}: {
  kind: ToolKind;
  args: Readonly<Record<string, unknown>>;
  output: string | null;
}) {
  const showArgs = SHOW_ARGS.has(kind) && Object.keys(args).length > 0;
  if (!showArgs && !output) return <p className="text-xs text-muted-foreground">没有输出</p>;
  return (
    <div className="space-y-2">
      {showArgs && (
        <pre className="max-h-60 overflow-auto rounded-lg bg-muted px-3 py-2 font-mono text-xs whitespace-pre-wrap text-muted-foreground">
          {JSON.stringify(args, null, 2)}
        </pre>
      )}
      {output && (
        <pre className="max-h-80 overflow-auto rounded-lg border border-border bg-card px-3 py-2 font-mono text-xs whitespace-pre-wrap">
          {output}
        </pre>
      )}
    </div>
  );
}

/**
 * 工具行（设计 2026-10-22 3.5）：箭头 + 图标 + 中文动词 + 摘要（命令、路径、检索词）+ 用时或状态，
 * 次要色、悬停变正文色；点开看详情。替代原来的工具卡片。
 */
export function ToolLine({ toolName, args, status, result, isError, artifact }: ToolCallView) {
  const extra = artifact as ToolArtifact | undefined;
  const state = stepState(result, isError, status, extra?.waiting ?? false, extra?.paused ?? false);
  const { verb, detail, kind } = toolLabel(toolName, args);
  const Icon = KIND_ICONS[kind];
  const output = result === undefined ? null : String(result);
  const decision = extra?.decision;
  // 拒绝、回复、停止的工具本来就没执行：只写决定，不再另写"出错""已中断"
  const showStatus = !decision || decision.tone === "success";
  // 退出码不是 0 的命令，deepagents 照样当成功返回：收起时也要看得出它失败了
  const exitCode = kind === "execute" ? executeExitCode(output, extra) : null;
  const failedExit = state === "success" && exitCode !== null && exitCode !== 0;
  const line = (
    <details className="group/tool text-[13px]">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-muted-foreground transition-colors hover:text-foreground">
        <ChevronRight
          aria-hidden="true"
          className="size-3.5 shrink-0 transition-transform group-open/tool:rotate-90"
        />
        <Icon aria-hidden="true" className="size-3.5 shrink-0" />
        <span className="shrink-0">{verb}</span>
        {detail && <span className="min-w-0 truncate font-mono text-foreground">{detail}</span>}
        {decision && <Decision decision={decision} />}
        {!showStatus ? (
          <span className="ml-auto" />
        ) : failedExit ? (
          <span className="ml-auto shrink-0 text-xs text-danger">{`退出码 ${exitCode}`}</span>
        ) : (
          <ToolStatus state={state} duration={toolDuration(state, extra)} />
        )}
      </summary>
      <div className="mt-2 mb-1 ml-1.5 border-l border-border pl-4">
        {kind === "execute" ? (
          <ExecuteDetails
            command={detail}
            output={output}
            exitCode={exitCode}
            stderr={extra?.stderr ?? ""}
          />
        ) : (
          <OtherDetails kind={kind} args={args} output={output} />
        )}
      </div>
    </details>
  );
  if (!decision?.editedArgs) return line;
  // 选了"修改后执行"：实际执行的参数直接显示，不用点开
  return (
    <div className="space-y-1.5">
      {line}
      <div className="ml-1.5 space-y-1 border-l border-border pl-4">
        <p className="text-xs text-muted-foreground">修改后的参数（实际执行的）</p>
        <pre className="max-h-48 overflow-auto rounded-lg bg-muted px-3 py-2 font-mono text-xs whitespace-pre-wrap">
          {JSON.stringify(decision.editedArgs, null, 2)}
        </pre>
      </div>
    </div>
  );
}

interface ToolPart extends ToolCallView {
  type: "tool-call";
}

/** 执行命令的退出码：事件里有就用它（设计 2026-10-23 5.4），旧历史退回解析输出末尾那一行。 */
function executeExitCode(output: string | null, extra: ToolArtifact | undefined): number | null {
  if (extra?.exitCode !== undefined) return extra.exitCode;
  return output === null ? null : parseExecuteOutput(output).exitCode;
}

/** 一组工具里出错的个数：拒绝、回复、停止的本来就没执行，不算出错；退出码不是 0 的命令算。 */
export function failedCount(tools: ToolCallView[]): number {
  return tools.filter((tool) => {
    const extra = tool.artifact as ToolArtifact | undefined;
    const decision = extra?.decision;
    const exitCode =
      tool.toolName === "execute"
        ? executeExitCode(tool.result === undefined ? null : String(tool.result), extra)
        : null;
    const failed = tool.isError || (exitCode !== null && exitCode !== 0);
    return failed && (!decision || decision.tone === "success");
  }).length;
}

/** 一组工具的用时：从最早开始到最晚结束；有没结束的、算不出用时的（见 spanOf）就不显示。 */
function groupDuration(tools: ToolPart[]): string | null {
  const spans = tools.map((tool) => spanOf(tool.artifact as ToolArtifact | undefined));
  if (spans.some((span) => span === null)) return null;
  const starts = spans.map((span) => span?.start ?? 0);
  const ends = spans.map((span) => span?.end ?? 0);
  return formatDuration(Math.max(0, Math.max(...ends) - Math.min(...starts)));
}

/** 工具组里有运行中的：写"正在<动词>…"（取最后一个运行中的）；都结束了为空。 */
export function runningLabel(
  tools: readonly {
    toolName: string;
    args: Readonly<Record<string, unknown>>;
    status: { type: string };
  }[],
): string | null {
  const running = tools.findLast((tool) => tool.status.type === "running");
  return running ? `正在${toolLabel(running.toolName, running.args).verb}…` : null;
}

/**
 * 同一轮里相邻的工具调用合成一组（设计 2026-10-22 3.5）：一行"读取了 1 个文件，运行了 1 条命令"，
 * 有运行中的接"· 正在<动词>…"，点开逐条显示；只有一个工具时直接显示那一行。
 */
export function ToolGroup({
  indices,
  children,
}: {
  indices: readonly number[];
  children: ReactNode;
}) {
  const parts = useAuiState(({ message }) => message.parts);
  if (indices.length < 2) return <>{children}</>;
  const tools = indices
    .map((index) => parts[index])
    .filter((part): part is typeof part & ToolPart => part?.type === "tool-call");
  const running = runningLabel(tools);
  const failed = failedCount(tools);
  const duration = running ? null : groupDuration(tools);
  const Icon = KIND_ICONS[toolLabel(tools[0]?.toolName ?? "", {}).kind];
  return (
    <details className="group/tools text-[13px]">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-muted-foreground transition-colors hover:text-foreground">
        <ChevronRight
          aria-hidden="true"
          className="size-3.5 shrink-0 transition-transform group-open/tools:rotate-90"
        />
        <Icon aria-hidden="true" className="size-3.5 shrink-0" />
        <span className="min-w-0 truncate">
          {summarizeTools(tools.map((tool) => tool.toolName))}
        </span>
        {running && (
          <span className="flex shrink-0 items-center gap-1">
            <LoaderCircle aria-hidden="true" className="size-3.5 animate-spin" />
            {running}
          </span>
        )}
        {failed > 0 && <span className="shrink-0 text-danger">{`${failed} 个出错`}</span>}
        {duration && <span className="ml-auto shrink-0 font-mono text-xs">{duration}</span>}
      </summary>
      <div className="mt-2.5 mb-1 ml-1.5 flex flex-col gap-2.5 border-l border-border pl-4">
        {children}
      </div>
    </details>
  );
}
