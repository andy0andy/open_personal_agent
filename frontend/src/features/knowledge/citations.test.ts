import { describe, expect, it } from "vitest";
import { citationTarget, linkKind } from "./citations";

describe("citationTarget", () => {
  it("只认 #kb-<条目 ID> 形式的出处链接", () => {
    expect(citationTarget("#kb-1f0c2a9e-0000-4000-8000-000000000001")).toBe(
      "1f0c2a9e-0000-4000-8000-000000000001",
    );
  });

  it("编号格式不对、普通网址、没有地址时不是出处", () => {
    expect(citationTarget("#kb-123")).toBeNull();
    expect(
      citationTarget("https://example.com/#kb-1f0c2a9e-0000-4000-8000-000000000001"),
    ).toBeNull();
    expect(citationTarget(undefined)).toBeNull();
  });
});

describe("linkKind", () => {
  it("出处、格式不对的出处（按普通文字显示）、普通链接", () => {
    expect(linkKind("#kb-1f0c2a9e-0000-4000-8000-000000000001")).toBe("citation");
    expect(linkKind("#kb-123")).toBe("broken-citation");
    expect(linkKind("https://example.com")).toBe("link");
    expect(linkKind(undefined)).toBe("link");
  });
});
