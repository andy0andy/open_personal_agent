import { describe, expect, it } from "vitest";
import { nextIndex } from "./menuKeys";

describe("菜单的上下方向键", () => {
  it("下方向键到下一项，到底回到第一项；上方向键反过来", () => {
    expect(nextIndex(0, 3, "ArrowDown")).toBe(1);
    expect(nextIndex(2, 3, "ArrowDown")).toBe(0);
    expect(nextIndex(0, 3, "ArrowUp")).toBe(2);
    expect(nextIndex(1, 3, "ArrowUp")).toBe(0);
  });

  it("焦点还不在菜单里时：向下到第一项，向上到最后一项", () => {
    expect(nextIndex(-1, 3, "ArrowDown")).toBe(0);
    expect(nextIndex(-1, 3, "ArrowUp")).toBe(2);
  });

  it("其他键、空菜单不动", () => {
    expect(nextIndex(0, 3, "Enter")).toBeNull();
    expect(nextIndex(0, 0, "ArrowDown")).toBeNull();
  });
});
