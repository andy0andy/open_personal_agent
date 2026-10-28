import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Plus, Terminal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { approvalSettingsQuery, mcpServersQuery } from "../../api/queries";
import type { McpServerInput } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { PageHeader } from "../../components/ui/PageHeader";
import { Panel } from "../../components/ui/Panel";
import { Switch } from "../../components/ui/Switch";
import { Tag } from "../../components/ui/Tag";
import { StatusDot } from "../../components/ui/StatusDot";
import { failureReason, kindOf, serverStatus, toolsChanged, toolsSignature } from "./mcp";
import { ServerDrawer } from "./ServerDrawer";
import { ToolsDrawer, serverTarget } from "./ToolsDrawer";

/** 抽屉每次打开都换一个 key，表单从头开始，不残留上次没保存的内容。 */
type Editing = { key: number; name: string | null };

const errorText = (exc: unknown) => (exc instanceof Error ? exc.message : String(exc));

/**
 * MCP 页（设计文档 7，原型 05）。改动写进 .workdata/config/（D21）：
 * 任何服务都能改、停用、删除（D22）；需要密钥的服务只提示要在 .env 里设置哪个变量。
 */
export function McpPage() {
  const queryClient = useQueryClient();
  const servers = useQuery(mcpServersQuery);
  const approvals = useQuery(approvalSettingsQuery);
  // 服务连上或工具数变了：重新取审批规则里的工具清单（积压小问题 E7）
  const signature = servers.data ? toolsSignature(servers.data.servers) : null;
  const seenSignature = useRef<string | null>(null);
  useEffect(() => {
    const changed = toolsChanged(seenSignature.current, signature);
    if (signature !== null) seenSignature.current = signature;
    if (changed) void queryClient.invalidateQueries({ queryKey: approvalSettingsQuery.queryKey });
  }, [signature, queryClient]);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [viewingTools, setViewingTools] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [toolError, setToolError] = useState<string | null>(null);
  const [reloaded, setReloaded] = useState(false);
  useEffect(() => {
    if (!reloaded) return;
    const timer = setTimeout(() => setReloaded(false), 3000);
    return () => clearTimeout(timer);
  }, [reloaded]);

  const list = servers.data?.servers ?? [];
  const names = list.map((server) => server.name);
  const connected = list.filter((server) => server.state === "connected");
  const toolCount = connected.reduce((sum, server) => sum + server.tools.length, 0);
  const editingServer = list.find((server) => server.name === editing?.name) ?? null;
  const toolsServer = list.find((server) => server.name === viewingTools);
  // 设置页的 MCP 状态与审批规则也用这几份数据：改完一起刷新
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["settings"] });
  const act = async (action: () => Promise<unknown>) => {
    setPageError(null);
    try {
      await action();
    } catch (exc) {
      setPageError(errorText(exc));
    }
    await refresh();
  };
  const save = async (inputs: McpServerInput[]) => {
    const [first] = inputs;
    await (editing?.name && first ? api.updateMcpServer(first) : api.addMcpServers(inputs));
    await refresh();
    setEditing(null);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title="MCP"
        subtitle={`已连接 ${connected.length} / 共 ${list.length} · 可用工具 ${toolCount}`}
        actions={
          <>
            {reloaded && <span className="text-xs text-muted-foreground">已重新加载</span>}
            <Button
              onClick={() =>
                void act(async () => {
                  await api.reloadSettings();
                  setReloaded(true);
                })
              }
            >
              重新加载
            </Button>
            <Button
              variant="primary"
              onClick={() =>
                setEditing((current) => ({ key: (current?.key ?? 0) + 1, name: null }))
              }
            >
              <Plus className="size-4" aria-hidden="true" />
              手动添加
            </Button>
          </>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[55rem] space-y-5 p-6">
          {servers.data?.config_error && (
            <p className="rounded-xl border border-danger bg-danger-soft px-4 py-3 text-sm">
              配置文件有误：{servers.data.config_error}
            </p>
          )}
          {pageError && <p className="text-sm text-danger">{pageError}</p>}
          {servers.isError && (
            <p className="text-sm text-danger">读不出 MCP 服务：{errorText(servers.error)}</p>
          )}
          <Panel title="我的 MCP 服务">
            {list.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {servers.isLoading
                  ? "加载中…"
                  : "还没有 MCP 服务，点右上角的“手动添加”（可以粘贴 JSON）"}
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {list.map((server) => {
                  const enabled = server.state !== "disabled";
                  const status = serverStatus(server);
                  const reason = failureReason(server);
                  const local = kindOf(server.transport) === "local";
                  return (
                    <li key={server.name} className="py-3 first:pt-0 last:pb-0">
                      <div className="flex items-center gap-3">
                        <Switch
                          checked={enabled}
                          label={`启用 ${server.name}`}
                          onChange={(next) =>
                            void act(() => api.setMcpServerEnabled(server.name, next))
                          }
                        />
                        <div className={`min-w-0 flex-1 ${enabled ? "" : "opacity-60"}`}>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm">{server.name}</span>
                            {/* 连接方式是中性的说明，不用颜色（颜色只表示状态，设计 2.1） */}
                            <Tag tone="outline">
                              {local ? (
                                <Terminal aria-hidden="true" className="size-3" />
                              ) : (
                                <Globe aria-hidden="true" className="size-3" />
                              )}
                              {local ? "本地进程" : "网络"}
                            </Tag>
                          </div>
                          <p
                            className="truncate text-xs text-muted-foreground"
                            title={serverTarget(server)}
                          >
                            {server.description || serverTarget(server)}
                          </p>
                        </div>
                        <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
                          <StatusDot tone={status.tone} pulse={status.pulse} />
                          {status.text}
                        </span>
                        <Button onClick={() => setViewingTools(server.name)}>查看工具</Button>
                        <Button
                          onClick={() =>
                            setEditing((current) => ({
                              key: (current?.key ?? 0) + 1,
                              name: server.name,
                            }))
                          }
                        >
                          编辑
                        </Button>
                      </div>
                      {reason && (
                        <p className="mt-2 ml-12 rounded-lg bg-danger-soft px-3 py-2 text-xs break-words">
                          {reason}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>
        </div>
      </div>
      {editing && (
        <ServerDrawer
          key={editing.key}
          editing={editingServer}
          existingNames={names.filter((name) => name !== editing.name)}
          onClose={() => setEditing(null)}
          onSave={save}
          onDelete={async () => {
            if (!editing.name) return;
            await api.deleteMcpServer(editing.name);
            await refresh();
            setEditing(null);
          }}
        />
      )}
      {toolsServer && (
        <ToolsDrawer
          server={toolsServer}
          tools={(approvals.data?.tools ?? []).filter((tool) => tool.server === toolsServer.name)}
          error={toolError}
          onClose={() => {
            setViewingTools(null);
            setToolError(null);
          }}
          onSetAction={(tool, action) => {
            setToolError(null);
            api
              .setToolAction(tool, action)
              .then(refresh)
              .catch((exc: unknown) => setToolError(errorText(exc)));
          }}
        />
      )}
    </div>
  );
}
