import { describe, expect, it } from "vitest";
import type { ApprovalAction, ToolDecision } from "../../api/types";
import type { ApprovalItem, ChatState } from "../../features/chat/reducer";
import {
  SUBAGENT_TOOL,
  itemState,
  stepState,
  toThreadMessages,
  type SubagentArtifact,
  type ToolArtifact,
} from "./adapter";

const fileUrl = (fileId: string, download: boolean) => `/f/${fileId}${download ? "?d" : ""}`;

const finished: ChatState = {
  running: false,
  items: [
    { kind: "user", id: "u1", text: "hi" },
    {
      kind: "tool",
      id: "tool-c1",
      name: "ls",
      args: { path: "/" },
      status: "success",
      output: "无文件",
    },
    { kind: "assistant", id: "msg-m1", text: "你好" },
    { kind: "user", id: "u2", text: "再来" },
    {
      kind: "error",
      id: "err-r2",
      text: "模型网关不可用",
      runId: "r2",
      errorKind: "gateway",
      retryable: true,
    },
  ],
};

describe("toThreadMessages", () => {
  it("用户消息之间的工具调用与回答合并为一条助手消息，顺序不变", () => {
    const messages = toThreadMessages(finished, fileUrl);
    expect(messages.map((message) => message.role)).toEqual([
      "user",
      "assistant",
      "user",
      "assistant",
    ]);
    expect(messages[1]?.content).toEqual([
      {
        type: "tool-call",
        toolCallId: "tool-c1",
        toolName: "ls",
        argsText: '{\n  "path": "/"\n}',
        result: "无文件",
        isError: false,
      },
      { type: "text", text: "你好" },
    ]);
  });

  it("失败的运行映射为带错误原因的未完成消息", () => {
    expect(toThreadMessages(finished, fileUrl)[3]?.status).toEqual({
      type: "incomplete",
      reason: "error",
      error: "模型网关不可用",
    });
  });

  it("发送失败时只有错误项，也能单独成为一条助手消息", () => {
    const state: ChatState = {
      running: false,
      items: [
        {
          kind: "error",
          id: "err-1",
          text: "请求失败：502",
          runId: "r1",
          errorKind: "gateway",
          retryable: true,
        },
      ],
    };
    expect(toThreadMessages(state, fileUrl)).toEqual([
      {
        id: "a-err-1",
        role: "assistant",
        content: [],
        status: { type: "incomplete", reason: "error", error: "请求失败：502" },
        // 报错卡片按它给按钮（设计 2026-10-23 4.5）
        metadata: {
          custom: {
            stopped: false,
            error: { runId: "r1", kind: "gateway", retryable: true },
          },
        },
      },
    ]);
  });

  it("重试过的失败轮是一行数据片段", () => {
    const state: ChatState = {
      running: false,
      items: [
        { kind: "user", id: "u1", text: "写报告" },
        { kind: "retried", id: "retried-r1", attempt: 1, text: "网关出错" },
        { kind: "assistant", id: "msg-m2", text: "写好了" },
      ],
    };
    const [, assistant] = toThreadMessages(state, fileUrl);
    expect(assistant?.content).toEqual([
      { type: "data-retried", data: { attempt: 1, text: "网关出错" } },
      { type: "text", text: "写好了" },
    ]);
  });

  it("进行中的最后一条助手消息标记为 running；工具未结束时没有结果", () => {
    const running: ChatState = {
      running: true,
      items: [
        { kind: "user", id: "u1", text: "hi" },
        { kind: "tool", id: "tool-c1", name: "ls", args: {}, status: "running", output: "" },
      ],
    };
    const [, assistant] = toThreadMessages(running, fileUrl);
    expect(assistant?.status).toEqual({ type: "running" });
    expect(assistant?.content).toEqual([
      { type: "tool-call", toolCallId: "tool-c1", toolName: "ls", argsText: "{}" },
    ]);
  });
});

const usage = (input: number) => ({
  caller: "main",
  requested_model: "m",
  actual_model: "m",
  input_tokens: input,
  output_tokens: 1,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  reasoning_tokens: 0,
  duration_ms: 10,
});

describe("思考用时", () => {
  const thinking = (startedAt?: string, endedAt?: string): ChatState["items"][number] => ({
    kind: "thinking",
    id: "think-t1",
    text: "想",
    ...(startedAt ? { startedAt } : {}),
    ...(endedAt ? { endedAt } : {}),
  });
  const partOf = (item: ChatState["items"][number], running = false) =>
    toThreadMessages({ running, items: [{ kind: "user", id: "u1", text: "hi" }, item] }, fileUrl)[1]
      ?.content[0];

  it("秒数由起止时间算出（四舍五入）", () => {
    expect(partOf(thinking("2026-10-22T08:00:00.000Z", "2026-10-22T08:00:06.400Z"))).toEqual({
      type: "data-thinking",
      data: { text: "想", seconds: 6, running: false },
    });
  });

  it("缺一端时没有秒数；还在运行、没结束的思考标为进行中", () => {
    expect(partOf(thinking("2026-10-22T08:00:00.000Z"))).toEqual({
      type: "data-thinking",
      data: { text: "想", seconds: null, running: false },
    });
    expect(partOf(thinking("2026-10-22T08:00:00.000Z"), true)).toEqual({
      type: "data-thinking",
      data: { text: "想", seconds: null, running: true },
    });
  });
});

describe("思考、子智能体、待办与用量的映射", () => {
  const state: ChatState = {
    running: false,
    items: [
      { kind: "user", id: "u1", text: "hi" },
      { kind: "thinking", id: "think-m1", text: "想一想" },
      { kind: "todos", id: "todos-r1", todos: [{ content: "查", status: "pending" }] },
      {
        kind: "subagent",
        id: "sub-c1",
        name: "general-purpose",
        description: "查天气",
        status: "success",
        output: "晴",
        items: [{ kind: "usage", id: "usage-2", usage: usage(5) }],
      },
      { kind: "assistant", id: "msg-m1", text: "今天晴" },
      { kind: "usage", id: "usage-1", usage: usage(100) },
    ],
  };

  it("思考为思考片段，待办为数据片段，子智能体为带内部步骤的工具调用片段", () => {
    const [, assistant] = toThreadMessages(state, fileUrl);
    expect(assistant?.content).toEqual([
      { type: "data-thinking", data: { text: "想一想", seconds: null, running: false } },
      { type: "data-todos", data: [{ content: "查", status: "pending" }] },
      {
        type: "tool-call",
        toolCallId: "sub-c1",
        toolName: SUBAGENT_TOOL,
        argsText: "查天气",
        artifact: {
          name: "general-purpose",
          description: "查天气",
          items: [{ kind: "usage", id: "usage-2", usage: usage(5) }],
        },
        result: "晴",
        isError: false,
      },
      { type: "text", text: "今天晴" },
    ]);
  });

  it("工具行的附加信息带上真正开始执行的时间（设计 2026-10-23 5.7）", () => {
    const withTool: ChatState = {
      running: false,
      items: [
        { kind: "user", id: "u1", text: "读" },
        {
          kind: "tool",
          id: "tool-c1",
          name: "read_file",
          args: { file_path: "/a" },
          status: "success",
          output: "内容",
          startedAt: "2026-10-14T08:00:00.000Z",
          runningAt: "2026-10-14T08:00:05.000Z",
          finishedAt: "2026-10-14T08:00:06.000Z",
          waited: true,
        },
      ],
    };
    const [, assistant] = toThreadMessages(withTool, fileUrl);
    const [part] = assistant?.content ?? [];
    expect(part).toMatchObject({
      type: "tool-call",
      artifact: { runningAt: "2026-10-14T08:00:05.000Z", waited: true },
    });
  });

  it("本轮用量合计包含子智能体的调用（只统计 token）", () => {
    const [, assistant] = toThreadMessages(state, fileUrl);
    expect(assistant?.metadata?.custom?.usage).toEqual({
      input_tokens: 105,
      output_tokens: 2,
      calls: [usage(5), usage(100)],
    });
  });

  it("停止的运行映射为已取消的未完成消息", () => {
    const stopped: ChatState = {
      running: false,
      items: [
        { kind: "user", id: "u1", text: "hi" },
        { kind: "assistant", id: "msg-m1", text: "写到一半" },
        { kind: "stopped", id: "stopped-r1" },
      ],
    };
    const [, assistant] = toThreadMessages(stopped, fileUrl);
    expect(assistant?.status).toEqual({ type: "incomplete", reason: "cancelled" });
    expect(assistant?.metadata?.custom?.stopped).toBe(true);
  });
});

describe("被中断调用的估算用量", () => {
  it("放进消息的自定义信息，与本轮实际用量分开", () => {
    const interruptedUsage = { input_tokens: 4600, output_tokens: 320 };
    const state: ChatState = {
      running: false,
      items: [
        { kind: "user", id: "u1", text: "hi" },
        { kind: "assistant", id: "msg-m1", text: "写到一半" },
        { kind: "stopped", id: "stopped-r1", interruptedUsage },
      ],
    };
    const [, assistant] = toThreadMessages(state, fileUrl);
    expect(assistant?.metadata?.custom).toEqual({
      usage: undefined,
      stopped: true,
      interruptedUsage,
    });
  });
});

describe("每轮耗时", () => {
  it("计时项放进消息的自定义信息，不是消息片段", () => {
    const timing = {
      kind: "timing" as const,
      id: "timing-r1",
      startedAt: "2026-10-14T08:00:00.000Z",
      finishedAt: "2026-10-14T08:00:23.400Z",
    };
    const state: ChatState = {
      running: false,
      items: [
        { kind: "user", id: "u1", text: "hi" },
        timing,
        { kind: "assistant", id: "msg-m1", text: "好" },
      ],
    };
    const [, assistant] = toThreadMessages(state, fileUrl);
    expect(assistant?.content).toEqual([{ type: "text", text: "好" }]);
    expect(assistant?.metadata?.custom?.timing).toEqual({
      startedAt: timing.startedAt,
      finishedAt: timing.finishedAt,
    });
  });
});

describe("产物文件", () => {
  it("文件项映射为文件数据片段，带文件名与打开、下载地址", () => {
    const state: ChatState = {
      running: false,
      items: [
        { kind: "user", id: "u1", text: "画图" },
        {
          kind: "file",
          id: "file-r1-f1",
          fileId: "f1",
          path: "outputs/图表/chart.png",
          size: 20,
          mediaType: "image/png",
        },
      ],
    };
    const [, assistant] = toThreadMessages(state, fileUrl);
    expect(assistant?.content).toEqual([
      {
        type: "data-file",
        data: {
          fileId: "f1",
          name: "chart.png",
          path: "outputs/图表/chart.png",
          size: 20,
          mediaType: "image/png",
          url: "/f/f1",
          downloadUrl: "/f/f1?d",
        },
      },
    ]);
  });
});

describe("工具与子智能体步骤的显示状态", () => {
  it("有结果按结果显示；没有结果时，所在消息还在运行才算运行中，否则是被停止或失败打断的", () => {
    expect(stepState("ok", false, { type: "complete" })).toBe("success");
    expect(stepState("boom", true, { type: "complete" })).toBe("error");
    expect(stepState(undefined, undefined, { type: "running" })).toBe("running");
    expect(stepState(undefined, undefined, { type: "incomplete" })).toBe("interrupted");
  });

  it("子智能体内部的步骤：子智能体已不在运行时，未结束的步骤显示为已中断", () => {
    expect(itemState("running", true)).toBe("running");
    expect(itemState("running", false)).toBe("interrupted");
    expect(itemState("success", false)).toBe("success");
    expect(itemState("error", true)).toBe("error");
  });
});

describe("用户消息的附件", () => {
  it("放进消息的自定义信息，显示为可点开的文件标签", () => {
    const state: ChatState = {
      running: false,
      items: [
        {
          kind: "user",
          id: "u1",
          text: "看看",
          attachments: [{ id: "f1", path: "uploads/销售.csv", media_type: "text/csv", size: 3 }],
        },
      ],
    };
    const [user] = toThreadMessages(state, fileUrl);
    expect(user?.metadata?.custom).toEqual({
      attachments: [{ fileId: "f1", name: "销售.csv", size: 3 }],
    });
  });
});

describe("已记住", () => {
  it("已记住项映射为记忆数据片段", () => {
    const state: ChatState = {
      running: false,
      items: [
        { kind: "user", id: "u1", text: "记住我对花生过敏" },
        { kind: "memory", id: "memory-k1", content: "用户对花生过敏", pinned: false },
      ],
    };
    const [, assistant] = toThreadMessages(state, fileUrl);
    expect(assistant?.content).toEqual([
      { type: "data-memory", data: { content: "用户对花生过敏", pinned: false } },
    ]);
  });
});

function action(callId: string, command = "ls"): ApprovalAction {
  return {
    call_id: callId,
    name: "execute",
    args: { command },
    server: null,
    description: "",
    allowed: ["approve", "edit", "reject"],
  };
}

describe("处理完的审批并入工具行", () => {
  // 一次审批里有两个操作：c1 跑完了，c2 被拒绝
  const handled = (
    status: ApprovalItem["status"],
    decisions?: ToolDecision[],
    callIds = ["c1", "c2"],
  ): ChatState => ({
    running: false,
    items: [
      { kind: "user", id: "u1", text: "做" },
      {
        kind: "tool",
        id: "tool-c1",
        name: "execute",
        args: { command: "ls" },
        status: "success",
        output: "a",
        waited: true,
      },
      {
        kind: "tool",
        id: "tool-c2",
        name: "execute",
        args: { command: "rm x" },
        status: "error",
        output: "rejected",
        waited: true,
      },
      {
        kind: "approval",
        id: "approval-r1-3",
        runId: "r1",
        seq: 3,
        status,
        requests: [
          {
            interrupt_id: "i1",
            agent_path: ["main"],
            actions: callIds.map((callId) => action(callId)),
          },
        ],
        ...(decisions ? { answers: [{ interrupt_id: "i1", decisions }] } : {}),
      },
    ],
  });
  const partsOf = (state: ChatState) =>
    toThreadMessages(state, fileUrl)[1]?.content as unknown as {
      type: string;
      artifact?: { decision?: unknown };
    }[];

  it("一个同意、一个拒绝：各自的工具行显示自己的决定，不再有审批卡片", () => {
    const parts = partsOf(handled("resolved", [{ type: "approve" }, { type: "reject" }]));
    expect(parts.map((part) => part.type)).toEqual(["tool-call", "tool-call"]);
    expect(parts[0]?.artifact?.decision).toEqual({ label: "已同意", tone: "success" });
    expect(parts[1]?.artifact?.decision).toEqual({ label: "已拒绝", tone: "danger" });
  });

  it("修改后执行带实际执行的参数；回复一句话写出那句话", () => {
    const parts = partsOf(
      handled("resolved", [
        { type: "edit", args: { command: "ls -la" } },
        { type: "reject", message: "别删" },
      ]),
    );
    expect(parts[0]?.artifact?.decision).toEqual({
      label: "已修改参数后执行",
      tone: "success",
      editedArgs: { command: "ls -la" },
    });
    expect(parts[1]?.artifact?.decision).toEqual({ label: "已回复：别删", tone: "muted" });
  });

  it("等待中被停止：已停止，未执行", () => {
    const parts = partsOf(handled("stopped"));
    expect(parts[0]?.artifact?.decision).toEqual({ label: "已停止，未执行", tone: "muted" });
    expect(parts[1]?.artifact?.decision).toEqual({ label: "已停止，未执行", tone: "muted" });
  });

  it("工具不在这一层（比如在子智能体里）：处理完仍显示审批的结果", () => {
    const parts = partsOf(handled("resolved", [{ type: "approve" }], ["c9"]));
    expect(parts.map((part) => part.type)).toEqual(["tool-call", "tool-call", "data-approval"]);
  });
});

describe("审批", () => {
  const waiting: ChatState = {
    running: false,
    items: [
      { kind: "user", id: "u1", text: "写文件" },
      {
        kind: "tool",
        id: "tool-c1",
        name: "files_write_file",
        args: { path: "/shared/a.txt" },
        status: "waiting",
        output: "",
      },
      {
        kind: "approval",
        id: "approval-r1-3",
        runId: "r1",
        seq: 3,
        requests: [],
        status: "pending",
      },
    ],
  };

  it("等你决定的审批照旧是数据片段 data-approval；它的工具不再单独显示一行", () => {
    const pending: ChatState = {
      ...waiting,
      items: waiting.items.map((item) =>
        item.kind === "approval"
          ? {
              ...item,
              requests: [{ interrupt_id: "i1", agent_path: ["main"], actions: [action("c1")] }],
            }
          : item,
      ),
    };
    const [, answer] = toThreadMessages(pending, fileUrl);
    const parts = answer?.content as { type: string; data?: unknown }[];
    expect(parts).toHaveLength(1);
    expect(parts[0]).toMatchObject({ type: "data-approval", data: { id: "approval-r1-3" } });
  });

  it("等待审批的步骤显示为等待审批", () => {
    expect(itemState("waiting", false)).toBe("waiting");
    expect(stepState(undefined, undefined, { type: "complete" }, true)).toBe("waiting");
  });

  it("等审批时同一轮里没结束的自动工具与子智能体标为等待中，不显示已中断", () => {
    const paused: ChatState = {
      running: false,
      items: [
        { kind: "user", id: "u1", text: "整理一下" },
        { kind: "tool", id: "tool-auto", name: "ls", args: {}, status: "running", output: "" },
        {
          kind: "subagent",
          id: "subagent-s1",
          name: "analyst",
          description: "算",
          status: "running",
          output: "",
          items: [
            { kind: "tool", id: "tool-in", name: "ls", args: {}, status: "running", output: "" },
          ],
        },
        {
          kind: "tool",
          id: "tool-ask",
          name: "execute",
          args: { command: "rm x" },
          status: "waiting",
          output: "",
        },
        {
          kind: "approval",
          id: "approval-r1-5",
          runId: "r1",
          seq: 5,
          requests: [{ interrupt_id: "i1", agent_path: ["main"], actions: [action("ask")] }],
          status: "pending",
        },
      ],
    };
    const [, answer] = toThreadMessages(paused, fileUrl);
    const calls = (
      answer?.content as readonly { type: string; toolCallId?: string; artifact?: unknown }[]
    ).filter((part) => part.type === "tool-call");
    const auto = calls.find((part) => part.toolCallId === "tool-auto");
    const sub = calls.find((part) => part.toolCallId === "subagent-s1");
    expect((auto?.artifact as ToolArtifact).paused).toBe(true);
    expect((sub?.artifact as SubagentArtifact).paused).toBe(true);
    const complete = { type: "complete" };
    expect(stepState(undefined, undefined, complete, false, true)).toBe("paused");
    expect(itemState("running", false, true)).toBe("paused");
    // 没有待处理的审批时照旧：停着的就是被打断的
    expect(stepState(undefined, undefined, complete)).toBe("interrupted");
  });
});

describe("插话（设计 2026-10-23 6.3）", () => {
  it("送达的插话是这一轮里的一个片段：不切开这一轮", () => {
    const state: ChatState = {
      running: false,
      items: [
        { kind: "user", id: "u1", text: "写一段介绍" },
        { kind: "assistant", id: "msg-m1", text: "好的" },
        { kind: "interjection", id: "interject-i1", text: "改成英文" },
        { kind: "assistant", id: "msg-m2", text: "OK" },
      ],
    };
    const messages = toThreadMessages(state, fileUrl);
    expect(messages.map((message) => message.role)).toEqual(["user", "assistant"]);
    expect(messages[1]?.content).toEqual([
      { type: "text", text: "好的" },
      { type: "data-interjection", data: { text: "改成英文", queued: false } },
      { type: "text", text: "OK" },
    ]);
  });

  it("没送达的插话标为没送达", () => {
    const state: ChatState = {
      running: false,
      items: [
        { kind: "user", id: "u1", text: "写" },
        { kind: "interjection", id: "undelivered-r1-0", text: "改成英文", undelivered: true },
      ],
    };
    const [, answer] = toThreadMessages(state, fileUrl);
    expect(answer?.content).toEqual([
      {
        type: "data-interjection",
        data: { text: "改成英文", queued: false, undelivered: true },
      },
    ]);
  });

  it("排队的插话显示在这一轮的末尾，标为已排队", () => {
    const state: ChatState = {
      running: true,
      items: [
        { kind: "user", id: "u1", text: "写" },
        { kind: "assistant", id: "msg-m1", text: "好的" },
      ],
      queued: [{ key: "q1", text: "改成英文" }],
    };
    const [, answer] = toThreadMessages(state, fileUrl);
    expect(answer?.content).toEqual([
      { type: "text", text: "好的" },
      { type: "data-interjection", data: { text: "改成英文", queued: true } },
    ]);
  });

  it("这一轮还没有任何回答时也能排上（单独成一条进行中的助手消息）", () => {
    const state: ChatState = {
      running: true,
      items: [{ kind: "user", id: "u1", text: "写" }],
      queued: [{ key: "q1", text: "改成英文" }],
    };
    const messages = toThreadMessages(state, fileUrl);
    expect(messages.map((message) => message.role)).toEqual(["user", "assistant"]);
    expect(messages[1]?.status).toEqual({ type: "running" });
  });
});
