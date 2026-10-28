import { describe, expect, it } from "vitest";
import { sendsInterjection } from "./interjectKey";

const enter = { key: "Enter", shiftKey: false, nativeEvent: { isComposing: false, keyCode: 13 } };

describe("运行中按回车送插话（设计 2026-10-23 6.3）", () => {
  it("运行中、不在等审批：回车送出", () => {
    expect(sendsInterjection(enter, true)).toBe(true);
  });

  it("输入法正在选字时的回车不算（审查 Minor 2：Safari 确认候选词时 isComposing 已是 false）", () => {
    expect(
      sendsInterjection({ ...enter, nativeEvent: { isComposing: true, keyCode: 229 } }, true),
    ).toBe(false);
    expect(
      sendsInterjection({ ...enter, nativeEvent: { isComposing: false, keyCode: 229 } }, true),
    ).toBe(false);
  });

  it("Shift+回车换行；不能插话时（没在运行、等审批）不拦", () => {
    expect(sendsInterjection({ ...enter, shiftKey: true }, true)).toBe(false);
    expect(sendsInterjection({ ...enter, key: "a" }, true)).toBe(false);
    expect(sendsInterjection(enter, false)).toBe(false);
  });
});
