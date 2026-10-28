import { describe, expect, it } from "vitest";
import { clampToViewport } from "./menu";

describe("菜单位置", () => {
  const menu = { width: 128, height: 80 };
  const viewport = { width: 1000, height: 600 };

  it("有空间时放在点击处", () => {
    expect(clampToViewport({ x: 100, y: 100 }, menu, viewport)).toEqual({ x: 100, y: 100 });
  });

  it("靠近右边或底边时收回窗口内，留出边距", () => {
    expect(clampToViewport({ x: 990, y: 590 }, menu, viewport)).toEqual({ x: 864, y: 512 });
  });
});
