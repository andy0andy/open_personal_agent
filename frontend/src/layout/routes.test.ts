import { describe, expect, it } from "vitest";
import { NAV_GROUPS, chatPath, pageTitle } from "./routes";

describe("页面地址", () => {
  it("对话页地址带会话 ID；没有会话时是 /chat", () => {
    expect(chatPath()).toBe("/chat");
    expect(chatPath(null)).toBe("/chat");
    expect(chatPath("abc")).toBe("/chat/abc");
  });

  it("侧栏分工作、管理两组（设计文档 3.1）", () => {
    expect(NAV_GROUPS.map((group) => group.title)).toEqual(["工作", "管理"]);
    expect(NAV_GROUPS.map((group) => group.items.map((item) => item.label))).toEqual([
      ["对话", "知识库", "用量"],
      ["模型", "技能", "MCP", "设置"],
    ]);
  });
});

describe("浏览器标签页的标题（积压小问题 F16）", () => {
  it("每页写页名；对话页写会话标题，没有标题写“新会话”", () => {
    expect(pageTitle("/models")).toBe("模型 · 个人智能体");
    expect(pageTitle("/skills")).toBe("技能 · 个人智能体");
    expect(pageTitle("/mcp")).toBe("MCP · 个人智能体");
    expect(pageTitle("/knowledge")).toBe("知识库 · 个人智能体");
    expect(pageTitle("/usage")).toBe("用量 · 个人智能体");
    expect(pageTitle("/settings")).toBe("设置 · 个人智能体");
    expect(pageTitle("/chat")).toBe("对话 · 个人智能体");
    expect(pageTitle("/chat/t1", "云南旅行")).toBe("云南旅行 · 个人智能体");
    expect(pageTitle("/chat/t1", "")).toBe("新会话 · 个人智能体");
    expect(pageTitle("/chat/t1")).toBe("对话 · 个人智能体"); // 会话还没取到
  });
});
