import { describe, expect, it } from "vitest";
import { closesOverlay, isTopLayer, popLayer, pushLayer } from "./escape";

describe("按 Esc 关弹层", () => {
  it("普通的 Esc 关", () => {
    expect(closesOverlay({ key: "Escape", isComposing: false, keyCode: 27 })).toBe(true);
  });

  it("输入法选字时按 Esc 只是取消候选词，不关（不然没填完的表单就丢了）", () => {
    expect(closesOverlay({ key: "Escape", isComposing: true, keyCode: 229 })).toBe(false);
    expect(closesOverlay({ key: "Escape", isComposing: false, keyCode: 229 })).toBe(false);
  });

  it("别的键不关", () => {
    expect(closesOverlay({ key: "Enter", isComposing: false, keyCode: 13 })).toBe(false);
  });
});

describe("几层弹层叠在一起（积压小问题 I10）", () => {
  it("只有最上面一层响应 Esc 与 Tab；关掉上面那层后下面那层接着响应", () => {
    const drawer = pushLayer();
    const confirm = pushLayer();
    expect(isTopLayer(confirm)).toBe(true);
    expect(isTopLayer(drawer)).toBe(false);
    popLayer(confirm);
    expect(isTopLayer(drawer)).toBe(true);
    popLayer(drawer);
  });
});
