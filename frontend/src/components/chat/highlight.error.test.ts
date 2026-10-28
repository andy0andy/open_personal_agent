import { describe, expect, it, vi } from "vitest";

vi.mock("lowlight", () => ({
  common: {},
  createLowlight: () => ({
    registered: () => true,
    highlight: () => {
      throw new Error("Could not find the language");
    },
  }),
}));

describe("highlight：着色出错时", () => {
  it("原样显示（返回 null），不让整个回答白屏", async () => {
    const { highlight } = await import("./highlight");
    expect(highlight("x = 1", "python")).toBeNull();
  });
});
