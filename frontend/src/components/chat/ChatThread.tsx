import {
  AssistantRuntimeProvider,
  AuiIf,
  ComposerPrimitive,
  ThreadPrimitive,
  useAuiState,
  useExternalStoreRuntime,
  type AppendMessage,
} from "@assistant-ui/react";
import { ArrowUp, CornerDownLeft, Sparkles, Square, Upload, X } from "lucide-react";
import { useEffect, useMemo, useState, type DragEvent, type ReactNode } from "react";
import { draftSaver, loadDraft } from "../../features/chat/drafts";
import type { ChatState } from "../../features/chat/reducer";
import { latestTodos } from "../../features/chat/todos";
import { pastedFiles, type PendingUpload } from "../../features/chat/uploads";
import { toThreadMessages, type FileUrl } from "./adapter";
import { sendsInterjection } from "./interjectKey";
import { ApprovalActionsContext, type ApprovalActions } from "./approvalActions";
import { OpenCitationContext } from "./citationActions";
import { OpenFileContext } from "./fileActions";
import { RetryActionsContext, type RetryActions } from "./retryActions";
import { TodoBar } from "./TodoBar";
import { AttachButton, UploadChips } from "./uploads";
import { AssistantMessage, UserMessage } from "./parts";

interface ChatThreadProps {
  state: ChatState;
  /** 输入框上方的提示（如发送失败的原因），可关闭。 */
  notice: string | null;
  onDismissNotice: () => void;
  /** 发送成功返回 true；失败返回 false 时输入框恢复原文（用户已在输入新内容时不覆盖）。 */
  onSend: (text: string) => Promise<boolean>;
  /** 运行中插话（设计 2026-10-23 6.3）：送出返回 true；失败返回 false 时输入框恢复原文。 */
  onInterject: (text: string) => Promise<boolean>;
  /** 没送达的插话放回输入框（id 变了才放，放在已输入的内容前面）。 */
  restore?: { id: number; text: string } | null;
  /** 停止进行中的运行。 */
  onCancel: () => Promise<void>;
  /** 产物文件的打开 / 下载地址（由页面按所在会话提供）。 */
  fileUrl: FileUrl;
  /** 在右侧文件面板里打开一个文件。 */
  onOpenFile: (fileId: string) => void;
  /** 在右侧面板里显示回答引用的一条出处（知识条目 ID）。 */
  onOpenCitation: (itemId: string) => void;
  /** 输入框上方待发送的文件；选中或拖进来的文件交给 onAddFiles 上传。 */
  uploads: PendingUpload[];
  onAddFiles: (files: File[]) => void;
  onRemoveUpload: (key: string) => void;
  /** 有等你处理的审批：不能发新消息，发送按钮换成停止按钮（设计文档 10.1）。 */
  waiting: boolean;
  /** 审批卡片上的提交与停止。 */
  approvalActions: ApprovalActions;
  /** 报错卡片上的重试、换个模型再试。 */
  retryActions: RetryActions;
  /** 输入框下方紧贴的工具条（权限、用量、模型），由调用方提供 */
  toolbar?: ReactNode;
  /** 草稿按这个键（会话 ID）保存在浏览器本地；不传就不保存 */
  draftKey?: string;
}

const hasFiles = (event: DragEvent) => event.dataTransfer.types.includes("Files");

/** 对话区：消息列表 + 输入框。assistant-ui 只在 components/chat/ 这一层使用（设计文档 13.1）。 */
export function ChatThread({
  state,
  notice,
  onDismissNotice,
  onSend,
  onInterject,
  restore = null,
  onCancel,
  fileUrl,
  onOpenFile,
  onOpenCitation,
  uploads,
  onAddFiles,
  onRemoveUpload,
  waiting,
  approvalActions,
  retryActions,
  toolbar,
  draftKey,
}: ChatThreadProps) {
  const [dragging, setDragging] = useState(false);
  // 只在状态变化时重新转换：assistant-ui 按消息对象是否相同决定是否重新处理
  const messages = useMemo(() => toThreadMessages(state, fileUrl), [state, fileUrl]);
  // 这一轮还在进行（运行中或在等审批）时，待办进度显示在输入框上方（设计 2026-10-22 3.7）
  const todos = state.running || waiting ? latestTodos(state) : null;
  const runtime = useExternalStoreRuntime({
    messages,
    // 等待审批时也按"运行中"处理输入框：不能发送，只能停止
    isRunning: state.running || waiting,
    convertMessage: (message) => message,
    onNew: async (message: AppendMessage) => {
      const text = message.content.map((part) => (part.type === "text" ? part.text : "")).join("");
      const composer = runtime.thread.composer;
      if (!(await onSend(text)) && !composer.getState().text) composer.setText(text);
    },
    onCancel,
  });

  // 运行中（不在等审批）可以插话：回车或"插话"按钮把输入框里的话交给这一轮
  const canInterject = state.running && !waiting;
  const interject = async (): Promise<void> => {
    const composer = runtime.thread.composer;
    const text = composer.getState().text.trim();
    if (!text) return;
    composer.setText("");
    if (!(await onInterject(text)) && !composer.getState().text) composer.setText(text);
  };

  useEffect(() => {
    if (!restore) return;
    const composer = runtime.thread.composer;
    const typed = composer.getState().text;
    composer.setText(typed ? `${restore.text}\n${typed}` : restore.text);
  }, [restore, runtime]);

  // 草稿（设计 2026-10-22 3.10）：打开会话时输入框是空的才填回；输入停下 400ms 后保存，
  // 离开会话时把没来得及保存的也存上；发送后输入框清空，草稿随之删除
  useEffect(() => {
    if (!draftKey) return;
    const composer = runtime.thread.composer;
    if (!composer.getState().text) {
      const draft = loadDraft(draftKey);
      if (draft) composer.setText(draft);
    }
    const saver = draftSaver(draftKey);
    const unsubscribe = composer.subscribe(() => saver.update(composer.getState().text));
    return () => {
      unsubscribe();
      saver.flush();
    };
  }, [draftKey, runtime]);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <OpenFileContext value={onOpenFile}>
        <OpenCitationContext value={onOpenCitation}>
          <ApprovalActionsContext value={approvalActions}>
            <RetryActionsContext value={retryActions}>
              <ThreadPrimitive.Root
                className="relative flex min-h-0 flex-1 flex-col"
                onDragOver={(event) => {
                  if (!hasFiles(event)) return;
                  event.preventDefault(); // 允许放下
                  setDragging(true);
                }}
                onDragLeave={(event) => {
                  // 移到对话区里的子元素上也会触发：只在真正离开对话区时收起提示
                  if (!event.currentTarget.contains(event.relatedTarget as Node | null))
                    setDragging(false);
                }}
                onDrop={(event) => {
                  if (!hasFiles(event)) return;
                  event.preventDefault();
                  setDragging(false);
                  onAddFiles([...event.dataTransfer.files]);
                }}
              >
                {dragging && (
                  <div className="pointer-events-none absolute inset-2 z-10 flex items-center justify-center gap-2 rounded-xl border-2 border-dashed border-primary/60 bg-background/80 text-foreground">
                    <Upload className="size-5" />
                    松开即可上传
                  </div>
                )}
                <ThreadPrimitive.Viewport className="flex flex-1 flex-col overflow-y-auto">
                  <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-8">
                    <ThreadPrimitive.Empty>
                      <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center text-muted-foreground">
                        <Sparkles className="size-8 text-warning" />
                        <p className="text-lg text-foreground">今天想做点什么？</p>
                        <p className="text-sm">输入问题开始对话，Enter 发送，Shift+Enter 换行</p>
                      </div>
                    </ThreadPrimitive.Empty>
                    <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
                  </div>
                </ThreadPrimitive.Viewport>
                <div className="mx-auto w-full max-w-3xl px-6 pb-6">
                  {todos && <TodoBar todos={todos} />}
                  {notice && (
                    <div
                      role="alert"
                      className="mb-2 flex items-center gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
                    >
                      <span className="flex-1">{notice}</span>
                      <button
                        aria-label="关闭提示"
                        className="rounded-md p-0.5 hover:bg-danger/10"
                        onClick={onDismissNotice}
                      >
                        <X className="size-3.5" />
                      </button>
                    </div>
                  )}
                  <ComposerPrimitive.Root className="rounded-xl border border-border bg-card p-2 shadow-lg focus-within:border-ring">
                    <UploadChips uploads={uploads} onRemove={onRemoveUpload} />
                    <div className="flex items-end gap-2">
                      <AttachButton onAddFiles={onAddFiles} />
                      <ComposerPrimitive.Input
                        autoFocus
                        rows={1}
                        placeholder={
                          waiting
                            ? "请先处理上面的审批，或点停止"
                            : canInterject
                              ? "运行中也能补充或改主意：回车插话"
                              : "给智能体发消息…"
                        }
                        // 运行中按回车是插话（assistant-ui 运行中不处理回车，先拦下）
                        onKeyDown={(event) => {
                          if (!sendsInterjection(event, canInterject)) return;
                          event.preventDefault();
                          void interject();
                        }}
                        // 粘贴截图等文件：当作附件上传（设计 2026-10-22 3.10）；只是文字时照常粘贴
                        onPaste={(event) => {
                          const files = pastedFiles(event.clipboardData);
                          if (files.length === 0) return;
                          event.preventDefault();
                          onAddFiles(files);
                        }}
                        className="max-h-48 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 outline-none placeholder:text-muted-foreground"
                      />
                      <AuiIf condition={({ thread }) => !thread.isRunning}>
                        <ComposerPrimitive.Send
                          aria-label="发送"
                          className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity disabled:opacity-30"
                        >
                          <ArrowUp className="size-4" />
                        </ComposerPrimitive.Send>
                      </AuiIf>
                      {canInterject && <InterjectButton onClick={() => void interject()} />}
                      <AuiIf condition={({ thread }) => thread.isRunning}>
                        <ComposerPrimitive.Cancel
                          aria-label="停止"
                          className="flex size-9 items-center justify-center rounded-lg border border-border text-foreground transition-colors hover:bg-muted"
                        >
                          <Square className="size-3.5 fill-current" />
                        </ComposerPrimitive.Cancel>
                      </AuiIf>
                    </div>
                  </ComposerPrimitive.Root>
                  {toolbar}
                </div>
              </ThreadPrimitive.Root>
            </RetryActionsContext>
          </ApprovalActionsContext>
        </OpenCitationContext>
      </OpenFileContext>
    </AssistantRuntimeProvider>
  );
}

/** 运行中的"插话"按钮：输入框空着时不能点。 */
function InterjectButton({ onClick }: { onClick: () => void }) {
  const empty = useAuiState(({ composer }) => composer.text.trim() === "");
  return (
    <button
      type="button"
      aria-label="插话"
      title="把这句话交给正在进行的这一轮（回车）"
      disabled={empty}
      onClick={onClick}
      className="flex h-9 items-center gap-1 rounded-lg bg-primary px-3 text-sm text-primary-foreground transition-opacity disabled:opacity-30"
    >
      <CornerDownLeft className="size-4" />
      插话
    </button>
  );
}
