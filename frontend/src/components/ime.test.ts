import { describe, expect, it } from "vitest";
import { isImeComposing } from "./ime";

describe("输入法选字中的回车", () => {
  it("Chrome 用 isComposing、Safari 选字确认的回车 keyCode 为 229，都算在选字", () => {
    expect(isImeComposing({ isComposing: true, keyCode: 13 })).toBe(true);
    expect(isImeComposing({ isComposing: false, keyCode: 229 })).toBe(true);
  });

  it("普通回车不算", () => {
    expect(isImeComposing({ isComposing: false, keyCode: 13 })).toBe(false);
  });
});
