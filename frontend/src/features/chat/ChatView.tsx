import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { ApiError, api, fileContentUrl, readableError } from "../../api/client";
import { subscribeRun } from "../../api/events";
import {
  filesQuery,
  historyQuery,
  modelsQuery,
  threadUsageQuery,
  threadsQuery,
} from "../../api/queries";
import type {
  ApprovalAnswer,
  PermissionMode,
  RunAttachment,
  RunHistory,
  Thread,
  ThreadUpdate,
} from "../../api/types";
import { ChatThread } from "../../components/chat";
import { FilePanel } from "../files/FilePanel";
import { CitationPanel } from "../knowledge/CitationPanel";
import { markViewed } from "../threads/archive";
import { replaceThread } from "../threads/cache";
import { isAutoTitle, scheduleRefreshes } from "../threads/titleRefresh";
import { ChatHeader } from "./ChatHeader";
import { messageRunOf } from "./conversationLinks";
import { ComposerToolbar } from "./ComposerToolbar";
import { contextView } from "./context";
import { clearDraft } from "./drafts";
import {
  activeRun,
  addUserMessage,
  applyEvent,
  chatFromHistory,
  dropQueued,
  pendingApproval,
  queueInterjection,
  removeItem,
  roundCount,
  setApprovalStatus,
  type ApprovalItem,
  type ChatState,
} from "./reducer";
import { createGuard } from "./guard";
import { createSaveQueue } from "./saveQueue";
import { useSidePanel } from "./sidePanel";
import { useUploads } from "./useUploads";
import { keepScrolledTo } from "./scrollToTurn";
import { readyAttachments } from "./uploads";

function ChatSession({ thread, history }: { thread: Thread; history: RunHistory[] }) {
  const queryClient = useQueryClient();
  const models = useQuery(modelsQuery);
  const [state, setState] = useState<ChatState>(() => chatFromHistory(history));
  // 会话设置（D23）：模型与审批权限存在会话上，一改就保存；运行开始时由后端从会话上取
  const [model, setModel] = useState(thread.model);
  const [permission, setPermission] = useState<PermissionMode>(thread.permission_mode);
  // 会话的设置在别处变了（如模型页删掉了它的模型、另一个标签页改了权限）：跟着换
  const [threadModel, setThreadModel] = useState(thread.model);
  if (thread.model !== threadModel) {
    setThreadModel(thread.model);
    setModel(thread.model);
  }
  const [threadPermission, setThreadPermission] = useState(thread.permission_mode);
  if (thread.permission_mode !== threadPermission) {
    setThreadPermission(thread.permission_mode);
    setPermission(thread.permission_mode);
  }
  // 运行中或等待审批时改了权限：这次运行仍用开始时的档位，选择框旁提示
  const [pendingHint, setPendingHint] = useState(false);
  const saves = useRef(createSaveQueue());
  const retryGuard = useRef(createGuard());
  // 正在订阅的运行；afterSeq 之前的事件已经显示（来自界面历史）
  const [active, setActive] = useState(() => activeRun(history));
  // 发送、停止请求本身的失败（不是运行失败）：显示在输入框上方，不进对话
  const [notice, setNotice] = useState<string | null>(null);
  // 发送请求还没返回运行 ID 时就点了停止：拿到 ID 后立即停止
  const stopWhenStarted = useRef(false);
  const pending = useUploads(thread.id);
  // 插话（设计 2026-10-23 6.3）：排队的标识；没送达的放回输入框（id 每次加一，同样的话也会再放）
  const interjectSeq = useRef(0);
  const [restore, setRestore] = useState<{ id: number; text: string } | null>(null);
  const side = useSidePanel();
  // 顺利结束的运行次数：每次加一，触发下面检查标题是否还在等后台生成
  const [completedRuns, setCompletedRuns] = useState(0);
  const firstMessage = state.items.find((item) => item.kind === "user")?.text ?? "";
  const fileUrl = useCallback(
    (fileId: string, download: boolean) => fileContentUrl(thread.id, fileId, download),
    [thread.id],
  );

  // 打开会话就算看过了（设计 2026-10-23 6.5）
  useEffect(() => {
    void markViewed(queryClient, thread.id).catch(() => undefined);
  }, [queryClient, thread.id]);

  /** 以服务器为准重建对话，并接上进行中的运行（例如在另一个标签页发起的）。 */
  const resync = useCallback(async (): Promise<RunHistory[] | null> => {
    const latest = await api.history(thread.id).catch(() => null);
    if (!latest) return null;
    setState(chatFromHistory(latest));
    setActive(activeRun(latest));
    return latest;
  }, [thread.id]);

  /** 没送达的插话放回输入框，并提示。 */
  const giveBack = useCallback((texts: string[]): void => {
    setRestore((current) => ({ id: (current?.id ?? 0) + 1, text: texts.join("\n") }));
    setNotice("插话没送达，已放回输入框");
  }, []);

  useEffect(() => {
    if (!active) return;
    return subscribeRun(active.id, active.afterSeq, (event) => {
      setState((current) => applyEvent(current, event));
      if (event.type === "file.created") {
        void queryClient.invalidateQueries({ queryKey: filesQuery(thread.id).queryKey });
      }
      if (event.type === "approval.required" || event.type === "run.finished") {
        // file.created 推得比后台登记早，那时刷新可能还看不到；这两个事件之前登记都已写完
        void queryClient.invalidateQueries({ queryKey: filesQuery(thread.id).queryKey });
      }
      if (event.type === "approval.required") {
        setActive(null); // 推送已关闭：等你在审批卡片上决定后再订阅
        void queryClient.invalidateQueries({ queryKey: threadUsageQuery(thread.id).queryKey });
        void queryClient.invalidateQueries({ queryKey: threadsQuery.queryKey }); // 状态点改成待审批
      }
      if (event.type === "run.finished") {
        setActive(null);
        // 没送达的插话：失败、被停时放回输入框；顺利结束时后端已用它们发起下一轮，接上去
        const leftover = event.data.undelivered ?? []; // 旧历史没有
        if (leftover.length > 0) giveBack(leftover);
        if (event.data.next_run_id) void resync();
        void queryClient.invalidateQueries({ queryKey: threadUsageQuery(thread.id).queryKey });
        // 你正看着它跑完：先记下"看过了"，列表才不会亮"有新回答"；状态点随之消失或变红
        void markViewed(queryClient, thread.id)
          .catch(() => undefined)
          .finally(() => void queryClient.invalidateQueries({ queryKey: threadsQuery.queryKey }));
        if (event.data.status === "completed") setCompletedRuns((count) => count + 1);
      }
    });
  }, [active, giveBack, queryClient, resync, thread.id]);

  // 标题还是自动标题时，刷新几次会话列表等后台生成的标题；标题一变（或用户改了名）就不再刷新
  useEffect(() => {
    if (completedRuns === 0 || !isAutoTitle(thread.title, firstMessage)) return;
    return scheduleRefreshes(
      () => void queryClient.invalidateQueries({ queryKey: threadsQuery.queryKey }),
    );
  }, [completedRuns, firstMessage, queryClient, thread.title]);

  /** 运行中插话：先显示"已排队"，送达时由 user.interjected 换到送达的位置。 */
  const interject = async (text: string): Promise<boolean> => {
    if (!active) {
      setNotice("这一轮还在启动，稍等再插话");
      return false;
    }
    interjectSeq.current += 1;
    const key = `queued-${interjectSeq.current}`;
    setNotice(null);
    setState((current) => queueInterjection(current, key, text));
    try {
      await api.interject(active.id, text);
      clearDraft(thread.id);
      return true;
    } catch (error) {
      setState((current) => dropQueued(current, key));
      // 409 的原因（等审批、这一轮已结束）本身就是完整的提示
      setNotice(
        error instanceof ApiError && error.status === 409
          ? readableError(error)
          : `插话失败：${readableError(error)}`,
      );
      return false;
    }
  };

  const stop = async (runId: string): Promise<void> => {
    try {
      await api.cancelRun(runId);
    } catch (error) {
      setNotice(`停止失败：${readableError(error)}`);
    }
  };

  /** resend：重试时原样带上那条消息的文件（不动输入框上方待发送的文件）。 */
  const send = async (text: string, resend?: RunAttachment[]): Promise<boolean> => {
    // 刚换的模型、权限还在保存：等存好再发；存失败时（已提示并恢复原值）这条先不发
    if (!(await saves.current.idle())) return false;
    const files = resend ?? readyAttachments(pending.uploads);
    if (files === null) {
      setNotice("文件还在上传，请等上传完成再发送");
      return false;
    }
    const attachments = files.map(({ id, path, media_type, size }) => ({
      id,
      path,
      media_type,
      size,
    }));
    const userId = `user-${Date.now()}`;
    setNotice(null);
    stopWhenStarted.current = false;
    setState((current) => ({
      ...addUserMessage(current, userId, text, attachments),
      running: true,
    }));
    try {
      const run = await api.startRun(
        thread.id,
        text,
        files.map((file) => file.id),
      );
      // 发出的文件从输入框上方移走（发送途中新加的、失败的留着）
      if (!resend) {
        const sent = new Set(files.map((file) => file.id));
        pending.dropSent(sent);
      }
      setActive({ id: run.id, afterSeq: 0 });
      clearDraft(thread.id);
      if (stopWhenStarted.current) void stop(run.id);
      void queryClient.invalidateQueries({ queryKey: ["threads"] });
      return true;
    } catch (error) {
      setNotice(`发送失败：${readableError(error)}`);
      setState((current) => ({ ...removeItem(current, userId), running: false }));
      if (error instanceof ApiError && error.status === 409) void resync(); // 会话已有进行中的运行
      return false;
    } finally {
      stopWhenStarted.current = false;
    }
  };

  /** 提交审批决定：成功后从 approval.required 之后接着订阅推送。 */
  const answer = async (item: ApprovalItem, answers: ApprovalAnswer[]): Promise<void> => {
    setNotice(null);
    setState((current) => setApprovalStatus(current, item.id, "submitting"));
    try {
      await api.resumeRun(item.runId, answers);
      setActive({ id: item.runId, afterSeq: item.seq });
    } catch (error) {
      setState((current) => setApprovalStatus(current, item.id, "pending"));
      setNotice(`提交审批失败：${readableError(error)}`);
      // 已提交过或已失效（如在另一个标签页处理了）：以服务器为准重建
      if (error instanceof ApiError && error.status === 409) void resync();
    }
  };

  /** 停止一次等待审批的运行（没有推送在订阅）：停止后按界面历史重建，卡片显示"已停止"。 */
  const stopWaiting = async (runId: string): Promise<void> => {
    await stop(runId);
    const latest = await resync();
    // 等审批前排着的插话没送达：同样放回输入框
    const finished = latest
      ?.find((run) => run.id === runId)
      ?.events.findLast((event) => event.type === "run.finished");
    const leftover = finished?.type === "run.finished" ? (finished.data.undelivered ?? []) : [];
    if (leftover.length > 0) giveBack(leftover);
  };

  const waiting = pendingApproval(state);
  const busy = state.running || waiting !== null;
  if (!busy && pendingHint) setPendingHint(false);

  /** 会话设置一改就存：先在界面上换，存失败时提示并恢复原值（之后又改过的不动）。 */
  const saveSettings = (patch: ThreadUpdate, revert: () => void): void => {
    saves.current
      .run(async () => {
        await replaceThread(queryClient, await api.updateThread(thread.id, patch));
      })
      .catch((error: unknown) => {
        revert();
        setNotice(`保存失败：${readableError(error)}`);
      });
  };

  const changeModel = (next: string): void => {
    const previous = model;
    setModel(next);
    saveSettings({ model: next }, () =>
      setModel((current) => (current === next ? previous : current)),
    );
  };

  const changePermission = (next: PermissionMode): void => {
    const previous = permission;
    setPermission(next);
    if (busy) setPendingHint(true);
    saveSettings({ permission_mode: next }, () =>
      setPermission((current) => (current === next ? previous : current)),
    );
  };

  /** 停止当前运行；结果（已停止）随推送到达。 */
  const cancel = async (): Promise<void> => {
    if (active) await stop(active.id);
    else if (waiting) await stopWaiting(waiting.runId);
    else stopWhenStarted.current = true; // 发送请求还没返回
  };

  const approvalActions = useMemo(
    () => ({
      answer: (item: ApprovalItem, answers: ApprovalAnswer[]) => void answer(item, answers),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- answer 每次渲染重建，只按会话更新
    [thread.id],
  );

  // 报错卡片（设计 2026-10-23 4.5，D26）：重试这一轮由后端从运行前的存档分叉重跑，
  // 之后以服务器为准重建（失败的那一轮收成一行）并接上新运行；不能重试时 409，同样重建
  // 连点"重试这一轮"只发一次请求：第二次会得到 409，提示"重试失败"会让人以为没重试成
  const retryTurn = (runId: string): Promise<void> =>
    retryGuard.current.run(async () => {
      setNotice(null);
      try {
        await api.retryRun(runId);
      } catch (error) {
        setNotice(`重试失败：${readableError(error)}`);
      }
      await resync();
    });
  const retryActions = {
    retry: (runId: string) => {
      if (!busy) void retryTurn(runId);
    },
    continueTurn: () => {
      if (!busy) void send("继续");
    },
    switchModel: (next: string, runId: string, retryable: boolean) => {
      if (busy) return;
      changeModel(next);
      if (!retryable) {
        void send("继续"); // 发送前会等模型存好
        return;
      }
      // 重试由后端取会话的模型：等模型存好再发（存失败时已提示并恢复原值）
      void saves.current.idle().then((saved) => {
        if (saved) void retryTurn(runId);
      });
    },
    models: (models.data ?? [])
      .filter((item) => item.mode === "chat")
      .map((item) => ({ name: item.name, maxInputTokens: item.max_input_tokens ?? null })),
    current: model,
  };

  const rounds = roundCount(state);
  const maxInput = models.data?.find((item) => item.name === model)?.max_input_tokens ?? null;
  const context = contextView(state, maxInput);

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <ChatHeader
          thread={thread}
          rounds={rounds}
          filesOpen={side.filesOpen}
          onToggleFiles={side.toggleFiles}
        />
        <ChatThread
          state={state}
          notice={notice}
          onDismissNotice={() => setNotice(null)}
          onSend={send}
          onInterject={interject}
          restore={restore}
          onCancel={cancel}
          fileUrl={fileUrl}
          onOpenFile={side.openFile}
          onOpenCitation={side.openCitation}
          uploads={pending.uploads}
          onAddFiles={pending.add}
          onRemoveUpload={pending.remove}
          waiting={waiting !== null}
          approvalActions={approvalActions}
          retryActions={retryActions}
          draftKey={thread.id}
          toolbar={
            <ComposerToolbar
              threadId={thread.id}
              permission={permission}
              onPermission={changePermission}
              pendingHint={pendingHint}
              model={model}
              onModel={changeModel}
              context={context}
            />
          }
        />
      </div>
      {side.panel.open && side.panel.mode === "citation" && side.panel.itemId && (
        <CitationPanel key={side.panel.itemId} itemId={side.panel.itemId} onClose={side.close} />
      )}
      {side.filesOpen && (
        <FilePanel
          threadId={thread.id}
          selectedId={side.panel.fileId}
          onSelect={side.openFile}
          onClose={side.close}
        />
      )}
    </div>
  );
}

export function ChatView({ thread }: { thread: Thread }) {
  const history = useQuery(historyQuery(thread.id));
  const target = useSearchParams()[0].get("run");
  useEffect(() => {
    if (!target || !history.data) return;
    const runId = messageRunOf(target, history.data);
    // 长对话渲染、对话区自动滚到底要一会儿：滚过去后盯一会儿，被盖掉就再滚
    return keepScrolledTo(
      () => document.querySelector(`[data-message-id="user-${runId}"]`),
      window.innerHeight,
    );
  }, [target, history.data]);
  if (history.isError) {
    return <p className="p-6 text-sm text-danger">历史加载失败：{readableError(history.error)}</p>;
  }
  if (!history.data) {
    return (
      <p className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
        <LoaderCircle className="size-4 animate-spin" />
        加载中…
      </p>
    );
  }
  return <ChatSession key={thread.id} thread={thread} history={history.data} />;
}
