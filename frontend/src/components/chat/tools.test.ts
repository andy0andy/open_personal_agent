import { describe, expect, it } from "vitest";
import { parseExecuteOutput, summarizeTools, toolLabel } from "./tools";

describe("工具的中文名与摘要", () => {
  it.each([
    ["execute", { command: "ls -la" }, "执行命令", "ls -la", "execute"],
    ["read_file", { file_path: "/a.md" }, "读取文件", "/a.md", "read"],
    ["write_file", { file_path: "/b.md" }, "写入文件", "/b.md", "write"],
    ["edit_file", { file_path: "/c.md" }, "修改文件", "/c.md", "write"],
    ["ls", { path: "/workspace" }, "列出目录", "/workspace", "find"],
    ["glob", { pattern: "**/*.py" }, "查找文件", "**/*.py", "find"],
    ["grep", { pattern: "TODO" }, "搜索文件内容", "TODO", "find"],
    ["write_todos", { todos: [] }, "更新待办", "", "todos"],
    ["search_knowledge", { query: "花生" }, "检索知识库", "花生", "knowledge"],
    ["read_document", { item_id: "x" }, "读取文档", "", "knowledge"],
    ["remember", { content: "用户对花生过敏" }, "记住", "用户对花生过敏", "memory"],
    // 设计 2026-10-23 6.6
    [
      "update_memory",
      { old: "美式咖啡", new: "用户改喝茶" },
      "更正记忆",
      "用户改喝茶",
      "memory_change",
    ],
    ["forget_memory", { fragment: "猫叫咪咪" }, "忘掉记忆", "猫叫咪咪", "memory_change"],
    ["delete", { file_path: "/d.md" }, "删除文件", "/d.md", "write"],
    // 用量页的工具名（积压小问题 B12）
    ["task", { description: "查资料" }, "派出子智能体", "", "other"],
  ] as const)("%s → %s", (name, args, verb, detail, kind) => {
    expect(toolLabel(name, args)).toEqual({ verb, detail, kind });
  });

  it("MCP 服务的工具：外部工具 · 服务 · 工具", () => {
    expect(toolLabel("files_write_file", { path: "/a" })).toEqual({
      verb: "外部工具",
      detail: "files · write_file",
      kind: "external",
    });
  });

  it("不认识的工具显示原名", () => {
    expect(toolLabel("Mystery", {})).toEqual({ verb: "Mystery", detail: "", kind: "other" });
  });

  it("参数缺失或不是文字时摘要为空，不报错", () => {
    expect(toolLabel("execute", {})).toEqual({ verb: "执行命令", detail: "", kind: "execute" });
    expect(toolLabel("read_file", { file_path: 3 })).toMatchObject({ detail: "" });
  });
});

describe("一组工具的摘要", () => {
  it("按首次出现的顺序合计，用逗号连接", () => {
    expect(summarizeTools(["read_file", "execute", "read_file"])).toBe(
      "读取了 2 个文件，运行了 1 条命令",
    );
  });

  it("各类工具的说法", () => {
    expect(
      summarizeTools([
        "ls",
        "grep",
        "write_file",
        "search_knowledge",
        "remember",
        "write_todos",
        "files_list",
        "Mystery",
      ]),
    ).toBe(
      "查找了 2 次，改动了 1 个文件，检索了 1 次知识库，记下了 1 条记忆，更新了待办，" +
        "调用了 1 次外部工具，调用了 1 个工具",
    );
  });

  it("更正、忘掉记忆合在一起说", () => {
    expect(summarizeTools(["update_memory", "forget_memory"])).toBe("更正或忘掉了 2 条记忆");
  });
});

describe("执行命令的输出", () => {
  it("去掉末尾的退出码那一行，取出退出码", () => {
    expect(parseExecuteOutput("ok\n[Command succeeded with exit code 0]")).toEqual({
      text: "ok",
      exitCode: 0,
    });
    expect(parseExecuteOutput("boom\n[Command failed with exit code 2]")).toEqual({
      text: "boom",
      exitCode: 2,
    });
  });

  it("截断说明保留", () => {
    expect(
      parseExecuteOutput(
        "out\n[Command succeeded with exit code 0]\n[Output was truncated due to size limits]",
      ),
    ).toEqual({ text: "out\n[Output was truncated due to size limits]", exitCode: 0 });
  });

  it("没有输出、只有退出码", () => {
    expect(parseExecuteOutput("[Command succeeded with exit code 0]")).toEqual({
      text: "",
      exitCode: 0,
    });
  });

  it("旧记录没有退出码那一行：原文不变", () => {
    expect(parseExecuteOutput("plain")).toEqual({ text: "plain", exitCode: null });
  });
});

describe("查以前的对话单独算一类（积压小问题 B8）", () => {
  it("合计里写“查了 N 次以前的对话”，不算进知识库", () => {
    expect(summarizeTools(["search_conversations", "search_knowledge"])).toBe(
      "查了 1 次以前的对话，检索了 1 次知识库",
    );
  });
});
