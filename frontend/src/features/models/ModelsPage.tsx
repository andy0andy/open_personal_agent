import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  DatabaseZap,
  Eye,
  Layers,
  Plus,
  Trash2,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import { modelsAdminQuery } from "../../api/queries";
import type { ModelInput, ModelTestResult, ModelView } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { SelectField } from "../../components/ui/Field";
import { PageHeader } from "../../components/ui/PageHeader";
import { Panel } from "../../components/ui/Panel";
import { Tag } from "../../components/ui/Tag";
import { ModelDrawer } from "./ModelDrawer";
import { type Capability, canDelete, capabilitiesOf, modelMeta, selectableNames } from "./models";

// 能力标签是中性的说明（颜色只表示状态，设计 2.1），用图标区分
const CAPABILITIES: Record<Capability, { label: string; icon: LucideIcon }> = {
  thinking: { label: "思考", icon: Brain },
  vision: { label: "看图", icon: Eye },
  tools: { label: "工具", icon: Wrench },
  caching: { label: "缓存", icon: DatabaseZap }, // 提示缓存（设计 2026-10-23 4.1）
};

/** 删除按钮变淡时的原因。 */
function deleteBlocked(model: ModelView): string | null {
  if (model.is_default_chat) return "这是默认对话模型：先在上面换一个默认，再删它";
  if (model.is_default_embedding) return "知识库在用这个向量模型，不能删";
  return null;
}

type TestState = "running" | ModelTestResult;
const errorText = (exc: unknown) => (exc instanceof Error ? exc.message : String(exc));

/**
 * 模型页（设计文档 5，原型 03）。模型全部在网关数据库里（D22），增删改立即生效；
 * 首次启动导入的 4 个也能改、能删。向量模型（默认）只读（R31）。
 */
export function ModelsPage() {
  const queryClient = useQueryClient();
  const query = useQuery(modelsAdminQuery);
  const view = query.data;
  const defaultChat = view?.default_chat ?? "";
  const models = view?.models ?? [];
  // 测试结果按部署记：改名或删了再建同名的，不会显示旧结果
  const [tests, setTests] = useState<Record<string, TestState>>({});
  const [drawer, setDrawer] = useState<{ key: number; editing: ModelView | null } | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const testKey = (model: ModelView) => model.id ?? model.name;
  // 对话页的模型下拉框、会话列表（删掉模型后会话改用默认模型）也要跟着变
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["settings", "models"] }),
      queryClient.invalidateQueries({ queryKey: ["models"] }),
      queryClient.invalidateQueries({ queryKey: ["threads"], refetchType: "all" }),
    ]);
  const act = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
    } catch (exc) {
      setError(errorText(exc));
    }
    await refresh();
  };

  const runTest = async (model: ModelView) => {
    const key = testKey(model);
    setTests((current) => ({ ...current, [key]: "running" }));
    try {
      const result = await api.testModel(model.name);
      setTests((current) => ({ ...current, [key]: result }));
    } catch (exc) {
      setTests((current) => ({
        ...current,
        [key]: { ok: false, latency_ms: 0, error: errorText(exc) },
      }));
    }
  };
  const openDrawer = (editing: ModelView | null) =>
    setDrawer((current) => ({ key: (current?.key ?? 0) + 1, editing }));
  const save = async (input: ModelInput) => {
    await (drawer?.editing ? api.updateModel(input) : api.addModel(input));
    await refresh();
    setDrawer(null);
  };
  const target = models.find((model) => model.name === deleting);
  const chatModels = models.filter((model) => model.mode === "chat");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title="模型"
        subtitle={`${models.length} 个已登记`}
        actions={
          <>
            <Button
              onClick={() => void refresh()}
              title="改了 config/models.yaml 要先在终端执行 make restart-gateway"
            >
              刷新
            </Button>
            <Button variant="primary" disabled={!view} onClick={() => openDrawer(null)}>
              <Plus className="size-4" aria-hidden="true" />
              新增模型
            </Button>
          </>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[55rem] space-y-5 p-6">
          {(error ?? (query.isError ? errorText(query.error) : null)) && (
            <p className="text-sm text-danger">{error ?? errorText(query.error)}</p>
          )}
          <Panel title="默认模型" note="新会话的起点；对话里仍可按会话切换">
            <div className="grid grid-cols-2 gap-4">
              <SelectField
                label="对话模型"
                value={defaultChat}
                options={selectableNames(
                  chatModels.map((model) => model.name),
                  defaultChat,
                )}
                onChange={(name) => void act(() => api.setDefaultChatModel(name))}
              />
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">向量模型</p>
                <p className="flex h-9 items-center rounded-lg border border-border bg-muted px-2.5 font-mono text-sm">
                  {view?.default_embedding ?? ""}
                </p>
                <p className="text-xs text-muted-foreground">
                  换向量模型要重新向量化整个知识库，暂不支持在页面上改
                </p>
              </div>
            </div>
          </Panel>
          <Panel title="已登记模型">
            {models.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {query.isLoading ? "加载中…" : "网关里还没有模型"}
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {models.map((model) => {
                  const isDefault = model.is_default_chat || model.is_default_embedding;
                  const blocked = deleteBlocked(model);
                  const test = tests[testKey(model)];
                  return (
                    <li key={testKey(model)} className="py-3 first:pt-0 last:pb-0">
                      <div className="flex items-center gap-3">
                        <div className="min-w-0 flex-1 space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="truncate font-mono text-sm">{model.name}</span>
                            {isDefault && <Tag tone="solid">默认</Tag>}
                          </div>
                          <p
                            className="truncate text-xs text-muted-foreground"
                            title={modelMeta(model)}
                          >
                            {modelMeta(model)}
                          </p>
                        </div>
                        <div className="flex shrink-0 gap-1">
                          {model.mode === "embedding" ? (
                            <Tag>
                              <Layers aria-hidden="true" className="size-3" />
                              向量
                            </Tag>
                          ) : (
                            capabilitiesOf(model).map((capability) => {
                              const { label, icon: Icon } = CAPABILITIES[capability];
                              return (
                                <Tag key={capability}>
                                  <Icon aria-hidden="true" className="size-3" />
                                  {label}
                                </Tag>
                              );
                            })
                          )}
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <Button disabled={test === "running"} onClick={() => void runTest(model)}>
                            {test === "running" ? "测试中…" : "测试"}
                          </Button>
                          <Button onClick={() => openDrawer(model)}>编辑</Button>
                          {/* 按钮停用时不触发悬停：说明挂在外层 */}
                          <span title={blocked ?? undefined}>
                            <Button
                              variant="ghost"
                              aria-label={`删除 ${model.name}`}
                              title={blocked ?? `删除 ${model.name}`}
                              disabled={blocked !== null}
                              onClick={() => setDeleting(model.name)}
                            >
                              <Trash2 aria-hidden="true" className="size-3.5" />
                            </Button>
                          </span>
                        </div>
                      </div>
                      {/* 测试结果直接显示在这一行下面（设计 2026-10-22 第 4 节） */}
                      {test && test !== "running" && (
                        <p
                          className={`mt-2 rounded-lg px-3 py-2 text-xs break-words ${
                            test.ok ? "bg-success-soft" : "bg-danger-soft"
                          }`}
                        >
                          {test.ok
                            ? `✓ 可用 · ${test.latency_ms}ms`
                            : `✗ ${test.error ?? "测试失败"}`}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>
          <p className="text-xs text-muted-foreground">测试会真的调用一次模型，花几个 token。</p>
        </div>
      </div>
      {drawer && view && (
        <ModelDrawer
          key={drawer.key}
          editing={drawer.editing}
          sources={view.sources}
          otherNames={models
            .map((model) => model.name)
            .filter((name) => name !== drawer.editing?.name)}
          deletable={drawer.editing ? canDelete(drawer.editing) : false}
          onClose={() => setDrawer(null)}
          onDelete={() => drawer.editing && setDeleting(drawer.editing.name)}
          onSave={save}
        />
      )}
      <ConfirmDialog
        open={target !== undefined}
        title={`删除 ${deleting ?? ""}？`}
        confirmLabel="删除"
        danger
        onCancel={() => setDeleting(null)}
        onConfirm={() => {
          const name = deleting;
          setDeleting(null);
          setDrawer(null);
          if (name) void act(() => api.deleteModel(name));
        }}
      >
        <p>
          将从网关移除 {deleting}。有 {target?.sessions ?? 0} 个会话正在用它，之后会改用默认模型{" "}
          {view?.default_chat}；历史消息和用量保留。
        </p>
      </ConfirmDialog>
    </div>
  );
}
