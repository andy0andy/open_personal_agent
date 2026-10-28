import { describe, expect, it } from "vitest";
import type { McpServerView } from "../../api/types";
import {
  type ServerForm,
  formToInput,
  inputToForm,
  failureReason,
  parseMcpJson,
  pollWhileConnecting,
  serverStatus,
  toolsChanged,
  toolsSignature,
  validateServerForm,
} from "./mcp";

const FORM: ServerForm = {
  name: "notes2",
  description: "",
  kind: "local",
  command: "npx",
  args: "-y\nnotes-mcp",
  env: "TOKEN=${NOTES_TOKEN}",
  url: "",
  headers: "",
};

const view = (fields: Partial<McpServerView>): McpServerView => ({
  name: "files",
  description: "",
  transport: "stdio",
  state: "connected",
  error: null,
  tools: [],
  missing_env: [],
  config: { name: "files", description: "", transport: "stdio", args: [], env: {}, headers: {} },
  ...fields,
});

describe("识别粘贴的 JSON", () => {
  it("常见的 mcpServers 写法：有 command 的是本地进程，有 url 的是网络地址", () => {
    const text = JSON.stringify({
      mcpServers: {
        a: { command: "npx", args: ["x"], env: { K: "${K}" } },
        b: { url: "https://h/mcp", headers: { Authorization: "Bearer ${T}" } },
      },
    });
    expect(parseMcpJson(text)).toEqual({
      servers: [
        {
          name: "a",
          description: "",
          transport: "stdio",
          command: "npx",
          args: ["x"],
          env: { K: "${K}" },
          headers: {},
        },
        {
          name: "b",
          description: "",
          transport: "streamable_http",
          url: "https://h/mcp",
          args: [],
          env: {},
          headers: { Authorization: "Bearer ${T}" },
        },
      ],
    });
  });

  it("不带 mcpServers 外层的同样结构也认", () => {
    expect(parseMcpJson(JSON.stringify({ a: { command: "npx" } }))).toEqual({
      servers: [
        {
          name: "a",
          description: "",
          transport: "stdio",
          command: "npx",
          args: [],
          env: {},
          headers: {},
        },
      ],
    });
  });

  it("写错时给出原因", () => {
    expect(parseMcpJson("{")).toEqual({ error: "不是有效的 JSON" });
    expect(parseMcpJson(JSON.stringify({ mcpServers: { c: {} } }))).toEqual({
      error: "c 缺少 command 或 url",
    });
    expect(parseMcpJson("[]")).toEqual({ error: "没找到 MCP 服务的配置" });
    expect(parseMcpJson(JSON.stringify({ mcpServers: { "my-memo": { command: "npx" } } }))).toEqual(
      { error: "my-memo：服务名只能用小写字母、数字和下划线，且以字母开头" },
    );
  });
});

describe("服务状态（圆点 + 文字，设计 2026-10-22 第 4 节）", () => {
  it("已连接 · N 个工具 / 连接中… / 没有连上 / 已停用", () => {
    expect(serverStatus(view({ tools: ["add_note", "list_notes"] }))).toEqual({
      tone: "success",
      text: "已连接 · 2 个工具",
      pulse: false,
    });
    expect(serverStatus(view({ state: "connecting" }))).toEqual({
      tone: "info",
      text: "连接中…",
      pulse: true,
    });
    expect(serverStatus(view({ state: "failed", error: "x" }))).toEqual({
      tone: "danger",
      text: "没有连上",
      pulse: false,
    });
    expect(serverStatus(view({ state: "disabled" }))).toEqual({
      tone: "idle",
      text: "已停用",
      pulse: false,
    });
  });

  it("断线重连中：蓝点呼吸，写“重连中…”（设计 2026-10-23 5.8）", () => {
    expect(serverStatus(view({ state: "reconnecting", tools: ["add_note"] }))).toEqual({
      tone: "info",
      text: "重连中…",
      pulse: true,
    });
  });

  it("有服务在连接或重连时每 3 秒刷新，否则每 30 秒看一次（断线时圆点如实变化）", () => {
    const servers = (...states: McpServerView["state"][]) => ({
      servers: states.map((state) => view({ state })),
    });
    expect(pollWhileConnecting(servers("connected", "connecting"))).toBe(3000);
    expect(pollWhileConnecting(servers("reconnecting", "failed"))).toBe(3000);
    expect(pollWhileConnecting(servers("connected", "failed", "disabled"))).toBe(30000);
    expect(pollWhileConnecting(undefined)).toBe(false);
  });

  it("没连上的原因写在行下：缺环境变量时说怎么补", () => {
    expect(failureReason(view({ state: "failed", missing_env: ["BRAVE_API_KEY"] }))).toBe(
      "缺少环境变量：BRAVE_API_KEY。在 .env 里设置，然后在终端执行 make restart",
    );
    expect(failureReason(view({ state: "failed", error: "找不到命令 x" }))).toBe(
      "出错：找不到命令 x",
    );
    expect(failureReason(view({}))).toBeNull();
  });
});

describe("手动添加的表单", () => {
  it("填全了没有错误", () => {
    expect(validateServerForm(FORM, ["files"])).toEqual({});
  });

  it("服务名必填、合规且不能重名；本地进程要有命令；网络地址要以 http(s) 开头", () => {
    expect(validateServerForm({ ...FORM, name: "" }, []).name).toBe("填写服务名");
    expect(validateServerForm({ ...FORM, name: "files" }, ["files"]).name).toBe("已有同名服务");
    for (const name of ["brave-search", "Files", "1files", "a".repeat(33)]) {
      expect(validateServerForm({ ...FORM, name }, []).name).toBe(
        "服务名只能用小写字母、数字和下划线，且以字母开头",
      );
    }
    expect(validateServerForm({ ...FORM, command: " " }, [])).toEqual({
      command: "填写启动命令",
    });
    expect(validateServerForm({ ...FORM, kind: "network", url: "h/mcp" }, [])).toEqual({
      url: "地址要以 http:// 或 https:// 开头",
    });
  });

  it("表单与请求体互转：参数每行一个，环境变量每行 KEY=VALUE，原样保留 ${变量}", () => {
    const input = formToInput(FORM);
    expect(input).toEqual({
      name: "notes2",
      description: "",
      transport: "stdio",
      command: "npx",
      args: ["-y", "notes-mcp"],
      env: { TOKEN: "${NOTES_TOKEN}" },
      headers: {},
    });
    expect(inputToForm(input)).toEqual(FORM);
  });

  it("网络地址：请求头每行 名称: 值；原来是 sse 的保持 sse", () => {
    const network: ServerForm = {
      ...FORM,
      kind: "network",
      url: "https://h/mcp",
      headers: "Authorization: Bearer ${T}",
    };
    const input = formToInput(network, { transport: "sse" });
    expect(input).toMatchObject({
      transport: "sse",
      url: "https://h/mcp",
      headers: { Authorization: "Bearer ${T}" },
    });
    expect(input.command).toBeUndefined();
  });
});

describe("连上以后刷新工具清单（积压小问题 E7）", () => {
  it("服务连上、或工具数变了，签名就变；什么都没变时签名不变", () => {
    const connecting = toolsSignature([view({ state: "connecting", tools: [] })]);
    const connected = toolsSignature([view({ state: "connected", tools: ["read_file"] })]);
    const more = toolsSignature([view({ state: "connected", tools: ["read_file", "write_file"] })]);
    expect(new Set([connecting, connected, more]).size).toBe(3);
    expect(toolsSignature([view({ state: "connected", tools: ["read_file"] })])).toBe(connected);
  });

  it("只在签名真的变了时刷新：第一次取到服务列表不算（页面打开时已取过审批规则，审查 Minor 7）", () => {
    expect(toolsChanged(null, "a")).toBe(false);
    expect(toolsChanged("a", "a")).toBe(false);
    expect(toolsChanged("a", null)).toBe(false);
    expect(toolsChanged("a", "b")).toBe(true);
  });
});
