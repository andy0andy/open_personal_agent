import { describe, expect, it } from "vitest";
import { PENDING_HINT, PERMISSIONS, permissionOption } from "./permission";

describe("会话的审批权限（D23）", () => {
  it("三档依次为每次先问、只问执行命令、跳过所有审批，风险越大颜色越醒目", () => {
    expect(PERMISSIONS.map((p) => p.value)).toEqual(["ask", "ask_execute", "skip"]);
    expect(PERMISSIONS.map((p) => p.title)).toEqual(["每次先问", "只问执行命令", "跳过所有审批"]);
    expect(PERMISSIONS.map((p) => p.tone)).toEqual(["default", "warning", "danger"]);
    expect(PERMISSIONS.map((p) => p.description)).toEqual([
      "执行命令先问你；外部工具按 MCP 页的审批规则",
      "只有执行命令先问你，其余全部自动",
      "什么都不问（危险命令除外），直接执行，包括命令",
    ]);
  });

  it("按取值找到档位；运行中改了档位的提示", () => {
    expect(permissionOption("skip").title).toBe("跳过所有审批");
    expect(PENDING_HINT).toBe("从下一条消息开始生效");
  });
});

describe("跳过所有审批的说明（设计 2026-10-23 5.2）", () => {
  it("写明危险命令仍会问", () => {
    expect(permissionOption("skip").description).toBe(
      "什么都不问（危险命令除外），直接执行，包括命令",
    );
  });
});
