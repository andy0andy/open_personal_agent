/** 工具的类别：决定图标与一组工具的合计说法。 */
export type ToolKind =
  | "read"
  | "find"
  | "write"
  | "execute"
  | "knowledge"
  | "conversations"
  | "memory"
  | "memory_change"
  | "todos"
  | "external"
  | "other";

export interface ToolLabel {
  verb: string;
  /** 一段摘要：命令、文件路径、检索词等；没有时为空 */
  detail: string;
  kind: ToolKind;
}

// 内置工具：中文动词 + 取哪个参数做摘要（设计 2026-10-22 3.5）
const BUILTIN: Record<string, { verb: string; arg: string | null; kind: ToolKind }> = {
  execute: { verb: "执行命令", arg: "command", kind: "execute" },
  read_file: { verb: "读取文件", arg: "file_path", kind: "read" },
  write_file: { verb: "写入文件", arg: "file_path", kind: "write" },
  edit_file: { verb: "修改文件", arg: "file_path", kind: "write" },
  delete: { verb: "删除文件", arg: "file_path", kind: "write" },
  ls: { verb: "列出目录", arg: "path", kind: "find" },
  glob: { verb: "查找文件", arg: "pattern", kind: "find" },
  grep: { verb: "搜索文件内容", arg: "pattern", kind: "find" },
  write_todos: { verb: "更新待办", arg: null, kind: "todos" },
  // 对话里显示成子智能体卡片；这个名字给用量页的工具表用（积压小问题 B12）
  task: { verb: "派出子智能体", arg: null, kind: "other" },
  search_knowledge: { verb: "检索知识库", arg: "query", kind: "knowledge" },
  read_document: { verb: "读取文档", arg: null, kind: "knowledge" },
  remember: { verb: "记住", arg: "content", kind: "memory" },
  // 更正、忘掉记忆（设计 2026-10-23 6.6）
  update_memory: { verb: "更正记忆", arg: "new", kind: "memory_change" },
  forget_memory: { verb: "忘掉记忆", arg: "fragment", kind: "memory_change" },
  search_conversations: { verb: "查以前的对话", arg: "query", kind: "conversations" },
};

// MCP 服务的工具名是"服务名_工具名"（服务名只含小写字母、数字、连字符）
const EXTERNAL = /^([a-z0-9-]+)_(.+)$/;

/** 工具行的中文动词与摘要；MCP 工具显示"外部工具 · 服务 · 工具"，不认识的显示原名。 */
export function toolLabel(name: string, args: Record<string, unknown>): ToolLabel {
  const builtin = BUILTIN[name];
  if (builtin) {
    const value = builtin.arg ? args[builtin.arg] : undefined;
    return {
      verb: builtin.verb,
      detail: typeof value === "string" ? value : "",
      kind: builtin.kind,
    };
  }
  const external = EXTERNAL.exec(name);
  if (external) {
    return { verb: "外部工具", detail: `${external[1]} · ${external[2]}`, kind: "external" };
  }
  return { verb: name, detail: "", kind: "other" };
}

// 一组工具的合计说法（"更新了待办"不计次数）
const SUMMARY: Record<ToolKind, (count: number) => string> = {
  read: (n) => `读取了 ${n} 个文件`,
  find: (n) => `查找了 ${n} 次`,
  write: (n) => `改动了 ${n} 个文件`,
  execute: (n) => `运行了 ${n} 条命令`,
  knowledge: (n) => `检索了 ${n} 次知识库`,
  conversations: (n) => `查了 ${n} 次以前的对话`,
  memory: (n) => `记下了 ${n} 条记忆`,
  memory_change: (n) => `更正或忘掉了 ${n} 条记忆`,
  todos: () => "更新了待办",
  external: (n) => `调用了 ${n} 次外部工具`,
  other: (n) => `调用了 ${n} 个工具`,
};

/** 一组相邻工具调用的一行摘要：按类别首次出现的顺序合计，如"读取了 2 个文件，运行了 1 条命令"。 */
export function summarizeTools(names: string[]): string {
  const counts = new Map<ToolKind, number>();
  for (const name of names) {
    const { kind } = toolLabel(name, {});
    counts.set(kind, (counts.get(kind) ?? 0) + 1);
  }
  return [...counts].map(([kind, count]) => SUMMARY[kind](count)).join("，");
}

// deepagents 在执行命令的输出后追加的状态行
const EXIT_LINE = /\n?\[Command (?:succeeded|failed) with exit code (-?\d+)\]/g;

/** 执行命令的输出：去掉 deepagents 追加的"[Command … with exit code N]"一行，取出退出码。 */
export function parseExecuteOutput(output: string): { text: string; exitCode: number | null } {
  const matches = [...output.matchAll(EXIT_LINE)];
  const last = matches.at(-1);
  if (!last || last.index === undefined) return { text: output, exitCode: null };
  const text = output.slice(0, last.index) + output.slice(last.index + last[0].length);
  return { text: text.replace(/^\n/, ""), exitCode: Number(last[1]) };
}
