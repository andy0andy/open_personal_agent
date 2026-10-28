import { describe, expect, it } from "vitest";
import { actionLabel, serverStateLabel } from "./labels";

describe("设置页的文字", () => {
  it("MCP 服务的连接状态", () => {
    expect(serverStateLabel("disabled")).toBe("未启用");
    expect(serverStateLabel("connecting")).toBe("连接中");
    expect(serverStateLabel("connected")).toBe("已连接");
    expect(serverStateLabel("reconnecting")).toBe("重连中");
    expect(serverStateLabel("failed")).toBe("连接失败");
  });
  it("工具的审批方式", () => {
    expect(actionLabel("auto")).toBe("自动执行");
    expect(actionLabel("ask")).toBe("先问你");
  });
});
