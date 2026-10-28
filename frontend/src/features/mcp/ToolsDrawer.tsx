import { Button } from "../../components/ui/Button";
import { Drawer } from "../../components/ui/Drawer";
import { Tag } from "../../components/ui/Tag";
import type { McpServerView, ToolApproval } from "../../api/types";

/** 服务的启动命令或地址（编辑用的原文，密钥是 ${变量名}）。 */
export function serverTarget(server: McpServerView): string {
  const { config } = server;
  return config.transport === "stdio"
    ? [config.command ?? "", ...(config.args ?? [])].join(" ").trim()
    : (config.url ?? "");
}

/**
 * 查看工具的右侧抽屉（设计文档 7）：启动命令、没写规则时的默认做法，每个工具一行，
 * 带"只读"标签与"自动 / 先问"切换（写进 .workdata/config/approval_rules.yaml，D21）。
 */
export function ToolsDrawer({
  server,
  tools,
  error,
  onSetAction,
  onClose,
}: {
  server: McpServerView;
  tools: ToolApproval[];
  error: string | null;
  onSetAction: (tool: string, action: "auto" | "ask") => void;
  onClose: () => void;
}) {
  return (
    <Drawer title={`${server.name} 的工具`} open onClose={onClose}>
      <div className="space-y-1">
        <p className="text-xs text-muted-foreground">
          {server.config.transport === "stdio" ? "启动命令" : "地址"}
        </p>
        <pre className="overflow-x-auto border border-border bg-background p-2 font-mono text-xs">
          {serverTarget(server)}
        </pre>
      </div>
      <p className="text-xs text-muted-foreground">
        没写规则时：服务声明只读的工具自动执行，其余先问你。
        这里的规则只在会话权限为“每次先问”时起作用（D23）。
      </p>
      {error && <p className="text-xs text-danger">{error}</p>}
      {tools.length === 0 ? (
        <p className="text-sm text-muted-foreground">还没有工具（连上以后才知道）</p>
      ) : (
        <ul className="divide-y divide-border">
          {tools.map((tool) => (
            <li key={tool.name} className="flex items-center gap-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm">{tool.name}</span>
                  {tool.read_only && <Tag tone="success">只读</Tag>}
                </div>
                <p className="truncate text-xs text-muted-foreground">{tool.reason}</p>
              </div>
              <div className="flex shrink-0">
                {(
                  [
                    ["auto", "自动"],
                    ["ask", "先问"],
                  ] as const
                ).map(([action, label]) => (
                  <Button
                    key={action}
                    aria-pressed={tool.action === action}
                    variant={tool.action === action ? "primary" : "outline"}
                    onClick={() => onSetAction(tool.name, action)}
                  >
                    {label}
                  </Button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Drawer>
  );
}
