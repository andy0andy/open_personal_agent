import { describe, expect, it } from "vitest";
import type { SettingView } from "../../api/types";
import {
  groupSettings,
  parseInput,
  pendingRestartCount,
  rowBadge,
  sectionPending,
  uploadLimitMb,
} from "./settings";

const view = (key: string, extra: Partial<SettingView> = {}): SettingView => ({
  key,
  label: key,
  value: 1,
  upcoming: 1,
  default: 1,
  source: "default",
  env_name: key.replace(/\./g, "__").toUpperCase(),
  editable: true,
  apply: "restart",
  note: null,
  restart_pending: false,
  ...extra,
});

describe("设置页（D22）", () => {
  it("分节依次为对话与模型、工作区、知识库、只读项；.env 指定的留在原来那节", () => {
    const sections = groupSettings([
      view("agent.default_model", { apply: "now" }),
      view("agent.stream_idle_timeout", { source: "env", editable: false }),
      view("workspace.command_timeout"),
      view("max_upload_mb"),
      view("knowledge.recall_top_k"),
      view("knowledge.embedding_model", { editable: false, note: "要重新向量化" }),
      view("adapters.workspace", { editable: false }),
      view("models.sources", { editable: false }),
    ]);
    expect(sections.map((section) => [section.id, section.title])).toEqual([
      ["chat", "对话与模型"],
      ["workspace", "工作区"],
      ["knowledge", "知识库"],
      ["readonly", "只读项"],
    ]);
    expect(sections[0]?.items.map((item) => item.key)).toEqual([
      "agent.default_model",
      "agent.stream_idle_timeout",
    ]);
    expect(sections[1]?.items.map((item) => item.key)).toEqual([
      "workspace.command_timeout",
      "max_upload_mb",
    ]);
    expect(sections[3]?.items.map((item) => item.key)).toEqual([
      "knowledge.embedding_model",
      "adapters.workspace",
      "models.sources",
    ]);
  });

  it("生效时机每节说一次：都重启 / 都立即 / 混着的写明例外", () => {
    const [chat, workspace] = groupSettings([
      view("agent.default_model", { apply: "now" }),
      view("agent.recursion_limit"),
      view("workspace.command_timeout"),
    ]);
    expect(chat?.note).toBe("改了重启后生效（标着“立即生效”的除外）");
    expect(workspace?.note).toBe("改了重启后生效");
    expect(groupSettings([view("agent.default_model", { apply: "now" })])[0]?.note).toBe(
      "改了立即生效",
    );
  });

  it("待重启的项数与哪一节有待重启的项（导航上的琥珀点）", () => {
    const views = [
      view("agent.default_model"),
      view("workspace.command_timeout", { restart_pending: true }),
      view("max_upload_mb", { restart_pending: true }),
    ];
    expect(pendingRestartCount(views)).toBe(2);
    expect(pendingRestartCount([])).toBe(0);
    expect(sectionPending(views.slice(0, 1))).toBe(false);
    expect(sectionPending(views)).toBe(true);
  });

  it("行内徽章：已改且待重启 / 已改 / 没改不显示", () => {
    expect(rowBadge(view("a", { source: "db", restart_pending: true }))).toEqual({
      text: "已改 · 待重启",
      tone: "warning",
    });
    expect(rowBadge(view("a", { source: "db" }))).toEqual({ text: "已改", tone: "default" });
    expect(rowBadge(view("a"))).toBeNull();
  });

  it("数字项要填合法数字；文字项去掉首尾空白", () => {
    expect(parseInput(view("a", { value: 5 }), "abc")).toEqual({ ok: false, error: "请填数字" });
    expect(parseInput(view("a", { value: 5 }), "")).toEqual({ ok: false, error: "请填数字" });
    expect(parseInput(view("a", { value: 5 }), "30")).toEqual({ ok: true, value: 30 });
    expect(parseInput(view("a", { value: 0.3 }), "0.5")).toEqual({ ok: true, value: 0.5 });
    expect(parseInput(view("a", { value: "m" }), " x ")).toEqual({ ok: true, value: "x" });
  });
});

describe("被 .env 指定、又不属于任何一节的项（积压小问题 F19）", () => {
  it("放进只读项，不再整项消失", () => {
    const sections = groupSettings([
      view("agent.default_model"),
      view("adapters.workspace", { source: "env", editable: false }),
      view("models.sources", { source: "env", editable: false }),
    ]);
    const readonly = sections.find((section) => section.id === "readonly");
    expect(readonly?.items.map((item) => item.key)).toEqual([
      "adapters.workspace",
      "models.sources",
    ]);
  });
});

describe("上传上限（积压小问题 F6、F20）", () => {
  it("取设置里的 max_upload_mb；还没取到时为空", () => {
    expect(uploadLimitMb([view("max_upload_mb", { value: 30 })])).toBe(30);
    expect(uploadLimitMb(undefined)).toBeNull();
  });
});
