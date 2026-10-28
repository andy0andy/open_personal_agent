import type {
  McpProbeResult,
  McpServerInput,
  McpServerView,
  McpServersView,
} from "../../api/types";

export type ServerKind = "local" | "network";

export const kindOf = (transport: string): ServerKind =>
  transport === "stdio" ? "local" : "network";

// 与后端 config/integrations.py 的 _SERVER_NAME 一致：服务名也是工具名前缀，不合规的整份配置都加载不了
const SERVER_NAME = /^[a-z][a-z0-9_]{0,31}$/;
const SERVER_NAME_RULE = "服务名只能用小写字母、数字和下划线，且以字母开头";

export function serverNameError(name: string, existingNames: string[]): string | undefined {
  if (!name) return "填写服务名";
  if (!SERVER_NAME.test(name)) return SERVER_NAME_RULE;
  if (existingNames.includes(name)) return "已有同名服务";
  return undefined;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const stringMap = (value: unknown): Record<string, string> | undefined =>
  isRecord(value)
    ? Object.fromEntries(Object.entries(value).map(([k, v]) => [k, String(v)]))
    : undefined;

const BLANK = { description: "", args: [], env: {}, headers: {} };

/** 识别粘贴的配置：常见的 {"mcpServers": {...}}，也认不带外层的同样结构。${变量} 原样保留。 */
export function parseMcpJson(text: string): { servers: McpServerInput[] } | { error: string } {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { error: "不是有效的 JSON" };
  }
  if (!isRecord(data)) return { error: "没找到 MCP 服务的配置" };
  const map = isRecord(data.mcpServers) ? data.mcpServers : data;
  const entries = Object.entries(map);
  if (entries.length === 0) return { error: "没找到 MCP 服务的配置" };
  const servers: McpServerInput[] = [];
  for (const [name, config] of entries) {
    if (!SERVER_NAME.test(name)) return { error: `${name}：${SERVER_NAME_RULE}` };
    if (isRecord(config) && typeof config.command === "string") {
      const env = stringMap(config.env);
      servers.push({
        ...BLANK,
        name,
        transport: "stdio",
        command: config.command,
        args: Array.isArray(config.args) ? config.args.map(String) : [],
        env: env ?? {},
      });
    } else if (isRecord(config) && typeof config.url === "string") {
      const headers = stringMap(config.headers);
      servers.push({
        ...BLANK,
        name,
        transport: config.type === "sse" ? "sse" : "streamable_http",
        url: config.url,
        headers: headers ?? {},
      });
    } else {
      return { error: `${name} 缺少 command 或 url` };
    }
  }
  return { servers };
}

/** 服务状态（设计 2026-10-22 第 4 节）：圆点颜色 + 一句话；连接中的圆点会呼吸。 */
export function serverStatus(server: McpServerView): {
  tone: "success" | "info" | "danger" | "idle";
  text: string;
  pulse: boolean;
} {
  switch (server.state) {
    case "connected":
      return { tone: "success", text: `已连接 · ${server.tools.length} 个工具`, pulse: false };
    case "connecting":
      return { tone: "info", text: "连接中…", pulse: true };
    case "reconnecting": // 连上过、断开了，正在重连（设计 2026-10-23 5.8）
      return { tone: "info", text: "重连中…", pulse: true };
    case "failed":
      return { tone: "danger", text: "没有连上", pulse: false };
    case "disabled":
      return { tone: "idle", text: "已停用", pulse: false };
  }
}

/**
 * MCP 页多久刷新一次状态：有服务在连接或重连时每 3 秒；否则每 30 秒看一次
 * （后端每 30 秒 ping 一次，断线时圆点要如实变化，设计 2026-10-23 5.8）。
 */
export function pollWhileConnecting(data?: Pick<McpServersView, "servers">): number | false {
  if (!data) return false;
  const changing = data.servers.some(
    (server) => server.state === "connecting" || server.state === "reconnecting",
  );
  return changing ? 3000 : 30000;
}

/** 没连上的原因（写在这一行下面）；缺环境变量时说怎么补。 */
export function failureReason(server: McpServerView): string | null {
  if (server.state !== "failed") return null;
  return server.missing_env.length > 0
    ? `缺少环境变量：${server.missing_env.join("、")}。在 .env 里设置，然后在终端执行 make restart`
    : `出错：${server.error ?? "未知原因"}`;
}

export interface ServerForm {
  name: string;
  description: string;
  kind: ServerKind;
  command: string;
  args: string; // 每行一个
  env: string; // 每行 KEY=VALUE
  url: string;
  headers: string; // 每行 名称: 值
}

export function validateServerForm(
  form: ServerForm,
  existingNames: string[],
): Partial<Record<keyof ServerForm, string>> {
  const errors: Partial<Record<keyof ServerForm, string>> = {};
  const nameError = serverNameError(form.name.trim(), existingNames);
  if (nameError) errors.name = nameError;
  if (form.kind === "local" && !form.command.trim()) errors.command = "填写启动命令";
  if (form.kind === "network" && !/^https?:\/\//.test(form.url.trim())) {
    errors.url = "地址要以 http:// 或 https:// 开头";
  }
  return errors;
}

const lines = (text: string) =>
  text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

function pairs(text: string, separator: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const line of lines(text)) {
    const at = line.indexOf(separator.trim());
    const key = line.slice(0, at).trim();
    if (at > 0 && key) result[key] = line.slice(at + separator.trim().length).trim();
  }
  return result;
}

const joinPairs = (map: Record<string, string> | undefined, separator: string) =>
  Object.entries(map ?? {})
    .map(([key, value]) => `${key}${separator}${value}`)
    .join("\n");

/** 表单 → 请求体；网络服务原来用 sse 的保持 sse，其余用 streamable_http。 */
export function formToInput(
  form: ServerForm,
  base?: Pick<McpServerInput, "transport">,
): McpServerInput {
  const common = { name: form.name.trim(), description: form.description.trim() };
  if (form.kind === "local") {
    return {
      ...common,
      transport: "stdio",
      command: form.command.trim(),
      args: lines(form.args),
      env: pairs(form.env, "="),
      headers: {},
    };
  }
  return {
    ...common,
    transport: base?.transport === "sse" ? "sse" : "streamable_http",
    url: form.url.trim(),
    args: [],
    env: {},
    headers: pairs(form.headers, ": "),
  };
}

export function inputToForm(input: McpServerInput): ServerForm {
  return {
    name: input.name,
    description: input.description ?? "",
    kind: kindOf(input.transport ?? "stdio"),
    command: input.command ?? "",
    args: (input.args ?? []).join("\n"),
    env: joinPairs(input.env, "="),
    url: input.url ?? "",
    headers: joinPairs(input.headers, ": "),
  };
}

/** 测试连接的结果写成一句话 */
export function probeText(result: McpProbeResult): string {
  return result.ok ? `✓ 连接正常 · ${result.tools.length} 个工具` : (result.error ?? "连接失败");
}

/**
 * 服务的连接状态与工具数拼成的签名（积压小问题 E7）：变了就重新拉审批规则与工具清单——
 * 服务列表在连接中会轮询，规则不轮询，首次启动时连上后抽屉里一直是"还没有工具"。
 */
export function toolsSignature(servers: Pick<McpServerView, "name" | "state" | "tools">[]): string {
  return servers.map((server) => `${server.name}:${server.state}:${server.tools.length}`).join("|");
}

/** 工具清单是否变了：seen 是上次看到的签名，还没取到服务列表时两者为 null；第一次取到不算变。 */
export function toolsChanged(seen: string | null, signature: string | null): boolean {
  return seen !== null && signature !== null && seen !== signature;
}
