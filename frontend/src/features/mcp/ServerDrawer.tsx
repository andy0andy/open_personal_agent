import { useState } from "react";
import { api } from "../../api/client";
import type { McpServerInput, McpServerView } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { Drawer } from "../../components/ui/Drawer";
import { TextField } from "../../components/ui/Field";
import { Tabs } from "../../components/ui/Tabs";
import {
  formToInput,
  inputToForm,
  kindOf,
  parseMcpJson,
  probeText,
  type ServerForm,
  validateServerForm,
} from "./mcp";

type Tab = "local" | "network" | "json";

const KIND_LABELS = { local: "本地进程", network: "网络地址" } as const;
const SECRET_HINT = "密钥写成 ${变量名}，在 .env 里设置后执行 make restart";

const EMPTY: ServerForm = {
  name: "",
  description: "",
  kind: "local",
  command: "",
  args: "",
  env: "",
  url: "",
  headers: "",
};

/**
 * 手动添加 / 编辑 MCP 服务的右侧抽屉（设计文档 7）：本地进程、网络地址、粘贴 JSON 三个标签页。
 * 编辑时服务名不能改（它也是工具名前缀）；左下角可以删除（任何服务都能删，D22）。
 */
export function ServerDrawer({
  editing,
  existingNames,
  onSave,
  onDelete,
  onClose,
}: {
  editing: McpServerView | null;
  existingNames: string[];
  onSave: (servers: McpServerInput[]) => Promise<void>;
  onDelete: () => Promise<void>;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>(
    editing ? kindOf(editing.config.transport ?? "stdio") : "local",
  );
  const [form, setForm] = useState<ServerForm>(() =>
    editing ? inputToForm(editing.config) : EMPTY,
  );
  const [errors, setErrors] = useState<Partial<Record<keyof ServerForm, string>>>({});
  const [json, setJson] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const set = (key: keyof ServerForm, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  /** 每次都按文本框里现在的内容识别：识别后又改了文字，保存时用的也是改过的。 */
  const recognize = (): McpServerInput[] | null => {
    const result = parseMcpJson(json);
    if ("error" in result) {
      setNote(result.error);
      return null;
    }
    setNote(
      `识别到 ${result.servers.length} 个服务：${result.servers
        .map((server) => `${server.name}（${KIND_LABELS[kindOf(server.transport ?? "stdio")]}）`)
        .join("、")}`,
    );
    return result.servers;
  };

  /** 表单里的服务：先在本地校验，不合规就不发请求 */
  const formServer = (): McpServerInput | null => {
    const filled = { ...form, kind: tab === "network" ? "network" : "local" } as ServerForm;
    const found = validateServerForm(filled, editing ? [] : existingNames);
    setErrors(found);
    return Object.keys(found).length === 0 ? formToInput(filled, editing?.config) : null;
  };

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } catch (exc) {
      setNote(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const save = () =>
    run(async () => {
      if (tab === "json") {
        const parsed = recognize();
        const taken = parsed?.find((server) => existingNames.includes(server.name));
        if (taken) setNote(`已有同名服务：${taken.name}`);
        if (parsed && !taken) await onSave(parsed);
        return;
      }
      const server = formServer();
      if (server) await onSave([server]);
    });

  const test = () =>
    run(async () => {
      const server = tab === "json" ? recognize()?.[0] : formServer();
      if (server) setNote(probeText(await api.testMcpServer(server)));
    });

  return (
    <Drawer
      title={editing ? `编辑 ${editing.name}` : "手动添加 MCP 服务"}
      open
      onClose={onClose}
      footer={
        <>
          {editing ? (
            <Button variant="danger" disabled={busy} onClick={() => setConfirming(true)}>
              删除
            </Button>
          ) : null}
          <span className="flex-1" />
          <Button disabled={busy} onClick={() => void test()}>
            测试连接
          </Button>
          <Button variant="primary" disabled={busy} onClick={() => void save()}>
            保存并连接
          </Button>
        </>
      }
    >
      <Tabs
        tabs={[
          { id: "local", label: "本地进程" },
          { id: "network", label: "网络地址" },
          ...(editing ? [] : [{ id: "json", label: "粘贴 JSON" }]),
        ]}
        value={tab}
        onChange={(id) => setTab(id as Tab)}
      />
      {tab === "json" ? (
        <>
          <TextField
            label="配置 JSON"
            multiline
            hint={SECRET_HINT}
            placeholder='{"mcpServers": {"名称": {"command": "npx", "args": ["…"]}}}'
            value={json}
            onChange={setJson}
          />
          <Button onClick={() => void recognize()}>识别</Button>
        </>
      ) : (
        <>
          <TextField
            label="服务名"
            value={form.name}
            error={errors.name}
            disabled={editing !== null}
            hint={editing ? "服务名也是工具名的前缀，不能改" : undefined}
            onChange={(value) => set("name", value)}
          />
          <TextField
            label="描述（可空）"
            value={form.description}
            onChange={(value) => set("description", value)}
          />
          {tab === "local" ? (
            <>
              <TextField
                label="命令"
                placeholder="npx"
                value={form.command}
                error={errors.command}
                onChange={(value) => set("command", value)}
              />
              <TextField
                label="参数（每行一个）"
                multiline
                value={form.args}
                onChange={(value) => set("args", value)}
              />
              <TextField
                label="环境变量（每行 KEY=VALUE）"
                multiline
                hint={SECRET_HINT}
                value={form.env}
                onChange={(value) => set("env", value)}
              />
            </>
          ) : (
            <>
              <TextField
                label="地址"
                placeholder="https://example.com/mcp"
                value={form.url}
                error={errors.url}
                onChange={(value) => set("url", value)}
              />
              <TextField
                label="请求头（每行 名称: 值）"
                multiline
                hint={SECRET_HINT}
                value={form.headers}
                onChange={(value) => set("headers", value)}
              />
            </>
          )}
        </>
      )}
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
      {editing && (
        <ConfirmDialog
          title={`删除 ${editing.name}`}
          open={confirming}
          confirmLabel="删除"
          danger
          onConfirm={() => {
            setConfirming(false);
            void run(onDelete);
          }}
          onCancel={() => setConfirming(false)}
        >
          将断开并删除这个服务，它的工具的审批规则一起删掉。
        </ConfirmDialog>
      )}
    </Drawer>
  );
}
