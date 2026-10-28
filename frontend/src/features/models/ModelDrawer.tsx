import { useState } from "react";
import { api } from "../../api/client";
import type { ModelInput, ModelSource, ModelView } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { Drawer } from "../../components/ui/Drawer";
import { SelectField, TextField } from "../../components/ui/Field";
import {
  type Capability,
  type ModelForm,
  cachingAvailable,
  emptyModelForm,
  formToInput,
  modelToForm,
  validateModelForm,
} from "./models";

const CAPABILITIES: [Capability, string][] = [
  ["thinking", "思考"],
  ["vision", "看图"],
  ["tools", "工具"],
  ["caching", "提示缓存"], // 只对 Claude 显示（设计 2026-10-23 4.1）
];

/**
 * 新增 / 编辑模型的右侧抽屉（设计文档 5，用户选了抽屉而不是两步向导）。每次打开由使用方换 key，
 * 表单从空白（新增）或该模型当前的值（编辑）开始，关掉时没保存的内容就丢掉。
 * 存进网关数据库，立即生效（D21）；模型名不能改，密钥用来源里 .env 已有的那个。
 */
export function ModelDrawer({
  editing,
  sources,
  otherNames,
  deletable,
  onSave,
  onDelete,
  onClose,
}: {
  editing: ModelView | null;
  sources: ModelSource[];
  otherNames: string[];
  deletable: boolean;
  onSave: (input: ModelInput) => Promise<void>;
  onDelete: () => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<ModelForm>(() =>
    editing ? modelToForm(editing, sources) : emptyModelForm(sources[0]?.id ?? ""),
  );
  const [errors, setErrors] = useState<Partial<Record<keyof ModelForm, string>>>({});
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof ModelForm>(key: K, value: ModelForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));
  const source = sources.find((item) => item.id === form.source);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setNote(null);
    try {
      await action();
    } catch (exc) {
      setNote(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const save = () => {
    const found = validateModelForm(form, otherNames);
    setErrors(found);
    if (Object.keys(found).length === 0) void run(() => onSave(formToInput(form)));
  };

  const chat = form.kind === "chat";
  return (
    <Drawer
      title={editing ? `编辑 ${editing.name}` : "新增模型"}
      open
      onClose={onClose}
      footer={
        <>
          {editing && (
            <span title={deletable ? undefined : "先换掉默认再删"}>
              <Button variant="danger" disabled={!deletable || busy} onClick={onDelete}>
                删除
              </Button>
            </span>
          )}
          <span className="flex-1" />
          {editing && (
            <Button
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const result = await api.testModel(editing.name);
                  setNote(result.ok ? `✓ 可用 · ${result.latency_ms}ms` : `✗ ${result.error}`);
                })
              }
            >
              测试连接
            </Button>
          )}
          <Button variant="primary" disabled={busy} onClick={save}>
            保存
          </Button>
        </>
      }
    >
      <SelectField
        label="来源"
        value={source?.label ?? ""}
        options={sources.map((item) => item.label)}
        onChange={(label) => {
          const picked = sources.find((item) => item.label === label);
          if (picked) setForm((current) => ({ ...current, source: picked.id, kind: picked.mode }));
        }}
      />
      {source?.api_key && (
        <p className="text-xs text-muted-foreground">
          密钥用 .env 里已有的 {source.api_key.replace("os.environ/", "")}，页面上不填密钥
        </p>
      )}
      <TextField
        label="厂商模型 ID"
        value={form.vendorId}
        error={errors.vendorId}
        hint={source ? `转发时写成 ${source.prefix}${form.vendorId || "…"}` : undefined}
        onChange={(value) => set("vendorId", value)}
      />
      <TextField
        label="模型名"
        value={form.name}
        error={errors.name}
        disabled={editing !== null}
        hint={editing ? "模型名不能改：在用它的会话按名字对应" : "对话页的模型下拉框里显示这个名字"}
        onChange={(value) => set("name", value)}
      />
      <p className="text-xs text-muted-foreground">类型：{chat ? "对话" : "向量"}（随来源而定）</p>
      {chat && (
        <>
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">能力</p>
            <div className="flex gap-4 text-sm">
              {CAPABILITIES.filter(
                ([capability]) => capability !== "caching" || cachingAvailable(form.vendorId),
              ).map(([capability, label]) => (
                <label key={capability} className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={form.capabilities.includes(capability)}
                    onChange={(event) =>
                      set(
                        "capabilities",
                        event.target.checked
                          ? [...form.capabilities, capability]
                          : form.capabilities.filter((item) => item !== capability),
                      )
                    }
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <TextField
              label="上下文上限"
              inputMode="numeric"
              value={form.contextTokens}
              error={errors.contextTokens}
              onChange={(value) => set("contextTokens", value)}
            />
            <TextField
              label="输出上限"
              inputMode="numeric"
              value={form.outputTokens}
              error={errors.outputTokens}
              onChange={(value) => set("outputTokens", value)}
            />
          </div>
        </>
      )}
      <div className="space-y-2">
        <p className="text-xs text-muted-foreground">
          价格（美元 / 每百万 token；只做记录，不参与统计）
        </p>
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="输入价格"
            inputMode="decimal"
            disabled={form.free}
            value={form.priceInput}
            error={errors.priceInput}
            onChange={(value) => set("priceInput", value)}
          />
          <TextField
            label="输出价格"
            inputMode="decimal"
            disabled={form.free}
            value={form.priceOutput}
            error={errors.priceOutput}
            onChange={(value) => set("priceOutput", value)}
          />
        </div>
        <label className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={form.free}
            onChange={(event) => set("free", event.target.checked)}
          />
          免费
        </label>
      </div>
      {!editing && <p className="text-xs text-muted-foreground">保存后可以在列表里点"测试"</p>}
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
    </Drawer>
  );
}
