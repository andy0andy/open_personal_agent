import { describe, expect, it } from "vitest";
import type { ModelView } from "../../api/types";
import {
  type ModelForm,
  cachingAvailable,
  canDelete,
  emptyModelForm,
  formToInput,
  formatPrice,
  modelMeta,
  modelToForm,
  selectableNames,
  validateModelForm,
} from "./models";

const SOURCES = [
  { id: "upstream", label: "公司 LiteLLM 网关", mode: "chat", prefix: "litellm_proxy/" },
  { id: "ollama", label: "本机 Ollama", mode: "embedding", prefix: "ollama/" },
] as const;

const model = (fields: Partial<ModelView>): ModelView => ({
  name: "glm-5",
  mode: "chat",
  max_input_tokens: 200_000,
  input_cost_per_token: 0.000001,
  output_cost_per_token: 0.000002,
  supports_reasoning: false,
  supports_vision: true,
  id: "id-1",
  upstream: "litellm_proxy/glm-5",
  max_output_tokens: 32_000,
  supports_function_calling: true,
  supports_prompt_caching: false,
  source_label: "公司 LiteLLM 网关",
  sessions: 0,
  is_default_chat: false,
  is_default_embedding: false,
  ...fields,
});

const FORM: ModelForm = {
  source: "upstream",
  vendorId: "glm-5",
  name: "glm-5",
  kind: "chat",
  capabilities: ["vision", "tools"],
  contextTokens: "200000",
  outputTokens: "32000",
  free: false,
  priceInput: "1",
  priceOutput: "2",
};

describe("价格与一行说明", () => {
  it("价格按每百万 token 显示；两项都是 0 写免费；网关里没填的写价格未填", () => {
    expect(formatPrice(model({}))).toBe("$1 / $2 每百万");
    expect(formatPrice(model({ input_cost_per_token: 0, output_cost_per_token: 0 }))).toBe("免费");
    expect(formatPrice(model({ input_cost_per_token: null, output_cost_per_token: null }))).toBe(
      "价格未填",
    );
    expect(
      formatPrice(model({ input_cost_per_token: 0.000005, output_cost_per_token: 0.000025 })),
    ).toBe("$5 / $25 每百万");
  });

  it("对话模型写来源、上下文与输出上限；向量模型只写来源", () => {
    expect(modelMeta(model({}))).toBe(
      "公司 LiteLLM 网关 · 上下文 200k · 输出 32k · $1 / $2 每百万",
    );
    expect(
      modelMeta(model({ mode: "embedding", source_label: "本机 Ollama", max_input_tokens: null })),
    ).toBe("本机 Ollama · $1 / $2 每百万");
  });
});

describe("新增 / 编辑表单", () => {
  it("填全了没有错误", () => {
    expect(validateModelForm(FORM, [])).toEqual({});
  });

  it("每个模型都要有价格，或者标为免费；价格不能是负数、Infinity、十六进制", () => {
    expect(validateModelForm({ ...FORM, priceInput: "", priceOutput: "" }, []).priceInput).toBe(
      "填写价格，或标为免费",
    );
    for (const bad of ["-1", "Infinity", "0x10", "abc"]) {
      expect(validateModelForm({ ...FORM, priceInput: bad }, []).priceInput).toBe(
        "价格要是不小于 0 的数字",
      );
    }
    expect(validateModelForm({ ...FORM, free: true, priceInput: "" }, [])).toEqual({});
  });

  it("名字必填、合规且不能重名；厂商模型 ID 必填", () => {
    expect(validateModelForm({ ...FORM, name: "" }, []).name).toBe("填写模型名");
    expect(validateModelForm(FORM, ["glm-5"]).name).toBe("已有同名模型");
    expect(validateModelForm({ ...FORM, name: "带 空格" }, []).name).toBe(
      "模型名只能用字母、数字和 . _ : -，以字母或数字开头",
    );
    expect(validateModelForm({ ...FORM, vendorId: " " }, []).vendorId).toBe("填写厂商模型 ID");
  });

  it("对话模型的上下文与输出上限要是正整数；向量模型不填", () => {
    expect(validateModelForm({ ...FORM, contextTokens: "1.5" }, []).contextTokens).toBe(
      "填写正整数",
    );
    expect(
      validateModelForm(
        { ...FORM, kind: "embedding", source: "ollama", contextTokens: "", outputTokens: "" },
        [],
      ),
    ).toEqual({});
  });

  it("表单 → 请求体：价格仍按每百万（后端换算），能力转成各个开关", () => {
    expect(formToInput(FORM)).toEqual({
      name: "glm-5",
      source: "upstream",
      upstream_id: "glm-5",
      mode: "chat",
      max_input_tokens: 200000,
      max_output_tokens: 32000,
      price_input: 1,
      price_output: 2,
      supports_reasoning: false,
      supports_vision: true,
      supports_function_calling: true,
      supports_prompt_caching: false,
    });
    expect(formToInput({ ...FORM, free: true })).toMatchObject({ price_input: 0, price_output: 0 });
  });

  it("模型 → 表单：来源按前缀认出来，厂商 ID 去掉前缀", () => {
    expect(modelToForm(model({}), [...SOURCES])).toEqual(FORM);
    expect(emptyModelForm("upstream")).toMatchObject({ source: "upstream", kind: "chat" });
  });
});

describe("能不能删", () => {
  it("默认的不能删，其余都能删（D22）", () => {
    expect(canDelete(model({}))).toBe(true);
    expect(canDelete(model({ is_default_chat: true }))).toBe(false);
    expect(canDelete(model({ is_default_embedding: true }))).toBe(false);
  });
});

describe("提示缓存（设计 2026-10-23 4.1）", () => {
  it("只有 Claude 的模型才把缓存开关交给后端", () => {
    expect(formToInput({ ...FORM, capabilities: ["caching"] }).supports_prompt_caching).toBe(false);
    const claude = { ...FORM, vendorId: "claude-opus-4-6" };
    expect(formToInput({ ...claude, capabilities: ["caching"] }).supports_prompt_caching).toBe(
      true,
    );
    expect(formToInput({ ...claude, capabilities: [] }).supports_prompt_caching).toBe(false);
  });

  it("新建模型默认打开缓存", () => {
    expect(emptyModelForm("upstream").capabilities).toContain("caching");
  });

  it("编辑已有模型时按网关里的设置显示", () => {
    const cached = model({ upstream: "litellm_proxy/claude-x", supports_prompt_caching: true });
    expect(modelToForm(cached, SOURCES).capabilities).toContain("caching");
    expect(modelToForm(model({}), SOURCES).capabilities).not.toContain("caching");
  });

  it("厂商 ID 里带 claude（不分大小写）才显示开关", () => {
    expect(cachingAvailable("Claude-Opus-4-6")).toBe(true);
    expect(cachingAvailable("gemini-3.5-flash")).toBe(false);
  });
});

describe("默认对话模型的下拉框（积压小问题 F12）", () => {
  it("当前值不在对话模型里时也列出来，选择框不至于显示成别的模型", () => {
    expect(selectableNames(["a", "b"], "embed")).toEqual(["embed", "a", "b"]);
    expect(selectableNames(["a", "b"], "b")).toEqual(["a", "b"]);
    expect(selectableNames(["a"], "")).toEqual(["a"]);
  });
});
