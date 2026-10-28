import type { DataMessagePartComponent } from "@assistant-ui/react";
import { ShieldQuestion } from "lucide-react";
import { useContext, useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { ApprovalAction, ApprovalRequest } from "../../api/types";
import {
  REPLY_LIMIT,
  STOPPED_DECISION,
  approvalTitle,
  dangerOf,
  choiceKey,
  decisionView,
  parseEditedArgs,
  toAnswers,
  type Choice,
} from "../../features/chat/approvals";
import type { ApprovalItem } from "../../features/chat/reducer";
import { Button } from "../ui/Button";
import { closesOverlay } from "../ui/escape";
import { ApprovalActionsContext } from "./approvalActions";
import { toolLabel } from "./tools";

// 去掉沙箱容器后（D20、D23）命令跑在后端所在的环境里：同意前说清楚它碰得到什么
const EXECUTE_NOTE = "在本会话的目录里运行，能上网，也能读到项目里的大部分文件、连到本项目的数据库";
const KBD = "rounded border border-current/30 px-1 font-mono text-[11px] leading-4 opacity-70";

/**
 * 审批卡片（设计 2026-10-22 3.6；哪些操作要问看会话的审批权限，D23）：只在等你决定时出现，
 * 琥珀淡底 + 整圈琥珀边框。每个操作都选好后自动提交；只有一个操作时选完即提交。
 * 卡片出现时不抢焦点：用户可能正在输入框里打字，一个空格或回车不能变成"同意"（命令执行前唯一的一道关）。
 * 处理完以后决定并入对应的工具行，卡片不再显示（工具不在这一层时才在这里留一行结果）。
 */
export const ApprovalPart: DataMessagePartComponent = ({ data }) => {
  const item = data as ApprovalItem;
  const actions = useContext(ApprovalActionsContext);
  // 选择记在当时的卡片状态名下：提交失败、卡片回到待审批时自动清空，可以重新选
  const [picked, setPicked] = useState<{ status: string; choices: Record<string, Choice> }>({
    status: item.status,
    choices: {},
  });
  if (item.status === "resolved" || item.status === "stopped") {
    return <HandledApproval item={item} />;
  }
  const choices = picked.status === item.status ? picked.choices : {};
  const open = item.status === "pending";

  const choose = (key: string, choice: Choice) => {
    const next = { ...choices, [key]: choice };
    setPicked({ status: item.status, choices: next });
    const answers = toAnswers(item, next);
    if (answers) actions.answer(item, answers);
  };

  return (
    <div
      role="group"
      aria-label="等你确认"
      className="my-2 space-y-5 rounded-xl border border-warning bg-warning-soft p-4 text-sm"
    >
      {item.requests.map((request) => (
        <ToolRequest
          key={request.interrupt_id}
          item={item}
          request={request}
          open={open}
          onChoose={choose}
        />
      ))}
      {item.status === "submitting" && <p className="text-xs text-muted-foreground">提交中…</p>}
    </div>
  );
};

/** 处理完的审批，工具又不在这一层（如在子智能体里）：一行一个操作，写出决定。 */
function HandledApproval({ item }: { item: ApprovalItem }) {
  return (
    <div className="my-2 space-y-1.5 text-[13px] text-muted-foreground">
      {item.requests.flatMap((request) => {
        const answer = item.answers?.find((entry) => entry.interrupt_id === request.interrupt_id);
        return request.actions.map((action, index) => {
          const decision = answer?.decisions?.[index];
          const view =
            item.status === "stopped"
              ? STOPPED_DECISION
              : decision
                ? decisionView(action, decision)
                : null;
          const { verb, detail } = toolLabel(action.name, action.args);
          return (
            <div key={`${request.interrupt_id}-${index}`} className="space-y-1">
              <p className="flex items-center gap-2">
                <ShieldQuestion aria-hidden="true" className="size-3.5 shrink-0" />
                <span className="shrink-0">{verb}</span>
                {detail && (
                  <span className="min-w-0 truncate font-mono text-foreground">{detail}</span>
                )}
                {view && (
                  <span
                    title={view.label}
                    className={`min-w-0 truncate ${
                      view.tone === "success"
                        ? "text-success"
                        : view.tone === "danger"
                          ? "text-danger"
                          : ""
                    }`}
                  >
                    {view.label}
                  </span>
                )}
              </p>
              {view?.editedArgs && (
                <>
                  <p className="text-xs">修改后的参数（实际执行的）</p>
                  <pre className="max-h-48 overflow-auto rounded-lg bg-muted px-3 py-2 font-mono text-xs whitespace-pre-wrap text-foreground">
                    {JSON.stringify(view.editedArgs, null, 2)}
                  </pre>
                </>
              )}
            </div>
          );
        });
      })}
    </div>
  );
}

function ToolRequest({
  item,
  request,
  open,
  onChoose,
}: {
  item: ApprovalItem;
  request: ApprovalRequest;
  open: boolean;
  onChoose: (key: string, choice: Choice) => void;
}) {
  return (
    <>
      {request.actions.map((action, index) => (
        <ToolAction
          // 卡片状态变了（如提交失败回到待审批）就重新挂载：按钮、编辑框回到初始状态
          key={`${request.interrupt_id}-${index}-${item.status}`}
          action={action}
          open={open}
          onChoose={(choice) => onChoose(choiceKey(request.interrupt_id, index), choice)}
        />
      ))}
    </>
  );
}

function ToolAction({
  action,
  open,
  onChoose,
}: {
  action: ApprovalAction;
  open: boolean;
  onChoose: (choice: Choice) => void;
}) {
  const [mode, setMode] = useState<"buttons" | "edit" | "reply" | "chosen">("buttons");
  const [text, setText] = useState(() => JSON.stringify(action.args, null, 2));
  const [reply, setReply] = useState("");
  const parsed = parseEditedArgs(text);
  const { detail, kind } = toolLabel(action.name, action.args);
  const execute = kind === "execute";
  const danger = dangerOf(action); // 命中硬底线（设计 2026-10-23 5.2）
  const canReject = action.allowed.includes("reject");
  const chosenRef = useRef<HTMLParagraphElement>(null);
  const pick = (choice: Choice) => {
    setMode("chosen");
    onChoose(choice);
  };
  useEffect(() => {
    if (mode === "chosen") chosenRef.current?.focus();
  }, [mode]);
  // 焦点在这个操作里时 Esc = 拒绝；正在修改参数或写回复时 Esc 只是退回按钮。
  // 输入法选字时的 Esc 是取消候选词，不算（否则会直接拒绝或收起输入框）
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!closesOverlay(event.nativeEvent) || !open) return;
    if (mode === "edit" || mode === "reply") {
      event.preventDefault();
      setMode("buttons");
    } else if (mode === "buttons" && canReject) {
      event.preventDefault();
      pick({ type: "reject" });
    }
  };
  return (
    <div className="space-y-3" onKeyDown={onKeyDown}>
      <p className="flex items-center gap-2 font-medium text-foreground">
        <ShieldQuestion aria-hidden="true" className="size-4 shrink-0 text-warning" />
        {danger && <span className="text-danger">{`危险操作：${danger}`}</span>}
        {approvalTitle(action)}
      </p>
      {mode === "edit" && open ? (
        <div className="space-y-2">
          <textarea
            aria-label="修改参数"
            autoFocus
            value={text}
            onChange={(event) => setText(event.target.value)}
            rows={Math.min(12, text.split("\n").length + 1)}
            className="w-full resize-y rounded-lg border border-input bg-background px-3 py-2 font-mono text-[13px]"
          />
          {!parsed.ok && <p className="text-xs text-danger">{parsed.error}</p>}
          <div className="flex justify-end gap-2">
            <Button onClick={() => setMode("buttons")}>取消</Button>
            <Button
              variant="primary"
              disabled={!parsed.ok}
              onClick={() => pick({ type: "edit", text })}
            >
              确定，按新参数执行
            </Button>
          </div>
        </div>
      ) : (
        <pre className="max-h-48 overflow-auto rounded-lg border border-border bg-background px-3 py-2 font-mono text-[13px] break-all whitespace-pre-wrap">
          {execute ? (
            <>
              <span aria-hidden="true" className="text-muted-foreground">
                ${" "}
              </span>
              {detail}
            </>
          ) : (
            JSON.stringify(action.args, null, 2)
          )}
        </pre>
      )}
      {execute ? (
        <p className="text-xs text-muted-foreground">{EXECUTE_NOTE}</p>
      ) : (
        action.description && (
          <p className="line-clamp-3 text-xs text-muted-foreground">{action.description}</p>
        )
      )}
      {mode === "reply" && open && (
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (reply.trim()) pick({ type: "reply", message: reply });
          }}
        >
          <input
            aria-label="回复"
            autoFocus
            value={reply}
            onChange={(event) => setReply(event.target.value)}
            placeholder="告诉智能体该怎么做"
            maxLength={REPLY_LIMIT}
            className="h-8 min-w-0 flex-1 rounded-lg border border-input bg-background px-2.5 text-[13px]"
          />
          <Button onClick={() => setMode("buttons")}>取消</Button>
          <Button type="submit" variant="primary" disabled={!reply.trim()}>
            发送
          </Button>
        </form>
      )}
      {open && mode === "buttons" && (
        <div className="flex flex-wrap items-center justify-end gap-2">
          {canReject && (
            <>
              <Button variant="ghost" onClick={() => pick({ type: "reject" })}>
                拒绝
                <kbd aria-hidden="true" className={KBD}>
                  Esc
                </kbd>
              </Button>
              <Button onClick={() => setMode("reply")}>回复一句话</Button>
            </>
          )}
          {action.allowed.includes("edit") && (
            <Button onClick={() => setMode("edit")}>修改后执行</Button>
          )}
          {action.allowed.includes("approve") && (
            <Button variant="primary" onClick={() => pick({ type: "approve" })}>
              同意
              <kbd aria-hidden="true" className={KBD}>
                ↵
              </kbd>
            </Button>
          )}
        </div>
      )}
      {open && mode === "chosen" && (
        // 选完以后按钮没了：焦点留在这一行（不然掉到页面最外层），Tab 接着去下一个操作
        <p ref={chosenRef} tabIndex={-1} className="text-xs text-muted-foreground">
          已选择
        </p>
      )}
    </div>
  );
}
