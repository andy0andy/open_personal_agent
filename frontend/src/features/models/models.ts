import type { ModelInput, ModelSource, ModelView } from "../../api/types";
import { formatTokens } from "../usage/format";

export type ModelKind = "chat" | "embedding";
export type Capability = "thinking" | "vision" | "tools" | "caching";

const PER_MILLION = 1_000_000;
// 与后端 backend/models/schemas.py 一致：模型名也出现在接口地址里
const MODEL_NAME = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/;

const perMillion = (perToken: number) => Number((perToken * PER_MILLION).toPrecision(6));

/** 价格只是模型的配置信息，任何统计都不用它（用户 2026-10-18 决定）；网关里存的是"美元 / token"。 */
export function formatPrice(
  model: Pick<ModelView, "input_cost_per_token" | "output_cost_per_token">,
): string {
  const { input_cost_per_token: input, output_cost_per_token: output } = model;
  if (input == null || output == null) return "价格未填";
  if (input === 0 && output === 0) return "免费";
  return `$${perMillion(input)} / $${perMillion(output)} 每百万`;
}

/** 清单里每行的说明：来源 · 上下文与输出上限 · 价格 */
export function modelMeta(model: ModelView): string {
  const parts = [model.source_label];
  if (model.mode !== "embedding") {
    if (model.max_input_tokens) parts.push(`上下文 ${formatTokens(model.max_input_tokens)}`);
    if (model.max_output_tokens) parts.push(`输出 ${formatTokens(model.max_output_tokens)}`);
  }
  parts.push(formatPrice(model));
  return parts.join(" · ");
}

export function capabilitiesOf(model: ModelView): Capability[] {
  return [
    ...(model.supports_reasoning ? (["thinking"] as const) : []),
    ...(model.supports_vision ? (["vision"] as const) : []),
    ...(model.supports_function_calling ? (["tools"] as const) : []),
    ...(model.supports_prompt_caching ? (["caching"] as const) : []),
  ];
}

/** 提示缓存只对 Claude 生效（设计 2026-10-23 4.1）：厂商模型 ID 里带 claude 才显示开关。 */
export function cachingAvailable(vendorId: string): boolean {
  return /claude/i.test(vendorId);
}

/** 默认的不能删（设计文档 5：先换掉默认再删）；其余都能删（D22）。 */
export function canDelete(model: ModelView): boolean {
  return !model.is_default_chat && !model.is_default_embedding;
}

export interface ModelForm {
  source: string; // 来源 id
  vendorId: string;
  name: string;
  kind: ModelKind;
  capabilities: Capability[];
  contextTokens: string;
  outputTokens: string;
  free: boolean;
  priceInput: string;
  priceOutput: string;
}

const positiveInteger = (value: string) => /^[1-9]\d*$/.test(value.trim());
// 只认普通的十进制写法：Number() 会把 Infinity、0x10 也当成数
const notPrice = (value: string) =>
  !/^\d+(\.\d+)?$/.test(value.trim()) || !Number.isFinite(Number(value));

export function validateModelForm(
  form: ModelForm,
  otherNames: string[],
): Partial<Record<keyof ModelForm, string>> {
  const errors: Partial<Record<keyof ModelForm, string>> = {};
  const name = form.name.trim();
  if (!name) errors.name = "填写模型名";
  else if (!MODEL_NAME.test(name))
    errors.name = "模型名只能用字母、数字和 . _ : -，以字母或数字开头";
  else if (otherNames.includes(name)) errors.name = "已有同名模型";
  if (!form.vendorId.trim()) errors.vendorId = "填写厂商模型 ID";
  if (form.kind === "chat") {
    if (!positiveInteger(form.contextTokens)) errors.contextTokens = "填写正整数";
    if (!positiveInteger(form.outputTokens)) errors.outputTokens = "填写正整数";
  }
  if (!form.free) {
    if (!form.priceInput.trim() && !form.priceOutput.trim()) {
      errors.priceInput = "填写价格，或标为免费";
    } else {
      if (notPrice(form.priceInput)) errors.priceInput = "价格要是不小于 0 的数字";
      if (notPrice(form.priceOutput)) errors.priceOutput = "价格要是不小于 0 的数字";
    }
  }
  return errors;
}

export function emptyModelForm(source: string): ModelForm {
  return {
    source,
    vendorId: "",
    name: "",
    kind: "chat",
    capabilities: ["caching"], // 新增 Claude 模型时默认打开提示缓存（对别的模型不起作用）
    contextTokens: "",
    outputTokens: "",
    free: false,
    priceInput: "",
    priceOutput: "",
  };
}

/** 编辑页面加的模型：来源按网关里模型名的前缀认出来，厂商 ID 去掉前缀。 */
export function modelToForm(
  model: ModelView,
  sources: readonly Pick<ModelSource, "id" | "prefix">[],
): ModelForm {
  const upstream = model.upstream ?? model.name;
  const source = sources.find((item) => upstream.startsWith(item.prefix));
  const text = (value: number | null | undefined) => (value == null ? "" : String(value));
  const free = model.input_cost_per_token === 0 && model.output_cost_per_token === 0;
  const price = (value: number | null | undefined) =>
    free || value == null ? "" : String(perMillion(value));
  return {
    source: source?.id ?? "",
    vendorId: source ? upstream.slice(source.prefix.length) : upstream,
    name: model.name,
    kind: model.mode === "embedding" ? "embedding" : "chat",
    capabilities: capabilitiesOf(model),
    contextTokens: text(model.max_input_tokens),
    outputTokens: text(model.max_output_tokens),
    free,
    priceInput: price(model.input_cost_per_token),
    priceOutput: price(model.output_cost_per_token),
  };
}

/** 校验通过的表单 → 请求体；价格仍是"美元 / 每百万"，后端存进网关时换算。 */
export function formToInput(form: ModelForm): ModelInput {
  const chat = form.kind === "chat";
  return {
    name: form.name.trim(),
    source: form.source,
    upstream_id: form.vendorId.trim(),
    mode: form.kind,
    max_input_tokens: chat ? Number(form.contextTokens) : null,
    max_output_tokens: chat ? Number(form.outputTokens) : null,
    price_input: form.free ? 0 : Number(form.priceInput || 0),
    price_output: form.free ? 0 : Number(form.priceOutput || 0),
    supports_reasoning: chat && form.capabilities.includes("thinking"),
    supports_vision: chat && form.capabilities.includes("vision"),
    supports_function_calling: chat && form.capabilities.includes("tools"),
    supports_prompt_caching:
      chat && cachingAvailable(form.vendorId) && form.capabilities.includes("caching"),
  };
}

/**
 * 下拉框的选项：当前值不在可选的模型里时（如默认对话模型被改成了向量模型、被删掉）也列在最前，
 * 选择框照实显示，不会看起来像选了别的模型（积压小问题 F12）。
 */
export function selectableNames(names: string[], current: string): string[] {
  return current && !names.includes(current) ? [current, ...names] : names;
}
