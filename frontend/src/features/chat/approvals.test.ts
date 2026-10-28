import { describe, expect, it } from "vitest";
import type { ApprovalAction } from "../../api/types";
import type { ApprovalItem } from "./reducer";
import {
  approvalTitle,
  dangerOf,
  choiceKey,
  choiceLabel,
  executedArgs,
  parseEditedArgs,
  toAnswers,
} from "./approvals";

function item(requests: ApprovalItem["requests"]): ApprovalItem {
  return {
    kind: "approval",
    id: "approval-r1-3",
    runId: "r1",
    seq: 3,
    requests,
    status: "pending",
  };
}

const tool = item([
  {
    interrupt_id: "i1",
    agent_path: ["main"],
    actions: [
      {
        call_id: "c1",
        name: "files_write_file",
        args: { path: "/shared/a.txt", content: "你好" },
        server: "files",
        description: "files · 写文件",
        allowed: ["approve", "edit", "reject"],
      },
    ],
  },
]);

describe("parseEditedArgs", () => {
  it("接受 JSON 对象", () => {
    expect(parseEditedArgs('{"a":1}')).toEqual({ ok: true, args: { a: 1 } });
  });
  it("不是对象或不是合法 JSON 时给出原因", () => {
    const array = parseEditedArgs("[1]");
    const broken = parseEditedArgs("{");
    expect(array.ok).toBe(false);
    expect(broken.ok).toBe(false);
    if (!array.ok) expect(array.error).toContain("对象");
    // 只给一句中文（浏览器给的解析错误是英文，不显示）
    if (!broken.ok) expect(broken.error).toBe("不是合法的 JSON：检查引号、逗号和括号是否成对");
  });
});

describe("toAnswers", () => {
  const key = choiceKey("i1", 0);
  it("还有操作没选时为 null", () => {
    expect(toAnswers(tool, {})).toBeNull();
  });
  it("四种选择分别变成对应的决定", () => {
    expect(toAnswers(tool, { [key]: { type: "approve" } })).toEqual([
      { interrupt_id: "i1", decisions: [{ type: "approve" }] },
    ]);
    expect(toAnswers(tool, { [key]: { type: "edit", text: '{"path":"/shared/b.txt"}' } })).toEqual([
      { interrupt_id: "i1", decisions: [{ type: "edit", args: { path: "/shared/b.txt" } }] },
    ]);
    expect(toAnswers(tool, { [key]: { type: "reject" } })).toEqual([
      { interrupt_id: "i1", decisions: [{ type: "reject" }] },
    ]);
    expect(toAnswers(tool, { [key]: { type: "reply", message: " 先别写 " } })).toEqual([
      { interrupt_id: "i1", decisions: [{ type: "reject", message: "先别写" }] },
    ]);
  });
  it("修改的参数不合法、回复为空或超过 2000 字时为 null", () => {
    expect(toAnswers(tool, { [key]: { type: "edit", text: "{" } })).toBeNull();
    expect(toAnswers(tool, { [key]: { type: "reply", message: "  " } })).toBeNull();
    expect(toAnswers(tool, { [key]: { type: "reply", message: "长".repeat(2001) } })).toBeNull();
  });
});

describe("choiceLabel", () => {
  it("给出每种决定的说明", () => {
    expect(choiceLabel({ type: "approve" })).toBe("已同意");
    expect(choiceLabel({ type: "edit", args: {} })).toBe("已修改参数后执行");
    expect(choiceLabel({ type: "reject" })).toBe("已拒绝");
    expect(choiceLabel({ type: "reject", message: "先别写" })).toBe("已回复：先别写");
  });
});

describe("executedArgs", () => {
  const action = {
    call_id: "c1",
    name: "files_write_file",
    args: { path: "/shared/a.txt", content: "你好" },
    server: "files",
    description: "files · 写文件",
    allowed: ["approve" as const],
  };
  it("修改后执行时显示新参数，其余显示原参数", () => {
    expect(executedArgs(action, { type: "edit", args: { path: "/shared/b.txt" } })).toEqual({
      path: "/shared/b.txt",
    });
    expect(executedArgs(action, { type: "approve" })).toEqual(action.args);
    expect(executedArgs(action, undefined)).toEqual(action.args);
  });
});

describe("审批卡片的标题", () => {
  const action = (name: string, args: Record<string, unknown> = {}): ApprovalAction => ({
    call_id: "c1",
    name,
    args,
    server: null,
    description: "",
    allowed: ["approve"],
  });

  it("执行命令", () => {
    expect(approvalTitle(action("execute", { command: "ls" }))).toBe("要执行这条命令吗？");
  });

  it("外部工具写出服务与工具名", () => {
    expect(approvalTitle(action("demo_add_note", { text: "买牛奶" }))).toBe(
      "要调用 demo · add_note 吗？",
    );
  });

  it("内置工具用中文动词，参数在下面的块里", () => {
    expect(approvalTitle(action("write_file", { file_path: "/a.md" }))).toBe("要写入文件吗？");
  });

  it("不认识的工具写原名", () => {
    expect(approvalTitle(action("Mystery"))).toBe("要调用 Mystery 吗？");
  });
});

describe("硬底线（设计 2026-10-23 5.2）", () => {
  const action = (name: string, args: Record<string, unknown> = {}): ApprovalAction => ({
    call_id: "c1",
    name,
    args,
    server: null,
    description: "",
    allowed: ["approve"],
  });

  it("说明以“危险操作：”开头时取出命中的那一条", () => {
    const risky = {
      ...action("execute", { command: "rm -rf /" }),
      description: "危险操作：删除根目录或家目录",
    };
    expect(dangerOf(risky)).toBe("删除根目录或家目录");
    expect(dangerOf(action("execute", { command: "ls" }))).toBeNull();
  });
});
