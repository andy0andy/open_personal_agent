import { describe, expect, it } from "vitest";
import { focusAfterClose, nextFocusIndex } from "./dialogFocus";

describe("对话框里按 Tab（积压小问题 H1）", () => {
  it("Tab 到最后一个再按回到第一个；Shift+Tab 反过来", () => {
    expect(nextFocusIndex(0, 3, false)).toBe(1);
    expect(nextFocusIndex(2, 3, false)).toBe(0);
    expect(nextFocusIndex(0, 3, true)).toBe(2);
  });

  it("焦点不在对话框里的元素上时：Tab 到第一个，Shift+Tab 到最后一个", () => {
    expect(nextFocusIndex(-1, 3, false)).toBe(0);
    expect(nextFocusIndex(-1, 3, true)).toBe(2);
  });

  it("没有可聚焦的元素：停在对话框本身", () => {
    expect(nextFocusIndex(-1, 0, false)).toBe(-1);
  });
});

describe("关闭后焦点回到谁（审查 Minor 3）", () => {
  const element = (isConnected: boolean) => ({ isConnected }) as unknown as HTMLElement;
  const body = element(true);

  it("打开前的焦点还在页面上：回到它", () => {
    const button = element(true);
    expect(focusAfterClose(button, element(true), body)).toBe(button);
  });

  it("打开前的焦点是 body 或已被移除（菜单项随菜单关掉）：回到给定的按钮", () => {
    const trigger = element(true);
    expect(focusAfterClose(body, trigger, body)).toBe(trigger);
    expect(focusAfterClose(element(false), trigger, body)).toBe(trigger);
    expect(focusAfterClose(null, trigger, body)).toBe(trigger);
  });
});
