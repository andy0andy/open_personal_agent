import { describe, expect, it } from "vitest";
import { moveItem, pendingOrder, sameOrder } from "./order";

describe("拖拽排序", () => {
  const ids = ["a", "b", "c", "d"];

  it("拖到目标上方或下方", () => {
    expect(moveItem(ids, "d", "b", "before")).toEqual(["a", "d", "b", "c"]);
    expect(moveItem(ids, "a", "c", "after")).toEqual(["b", "c", "a", "d"]);
    expect(moveItem(ids, "b", "d", "after")).toEqual(["a", "c", "d", "b"]);
  });

  it("拖到自己身上或目标不存在时顺序不变", () => {
    expect(moveItem(ids, "b", "b", "before")).toEqual(ids);
    expect(moveItem(ids, "b", "x", "after")).toEqual(ids);
  });
});

describe("sameOrder", () => {
  it("拖完顺序没变（放回原处、拖到相邻位置的同一侧）时不需要保存", () => {
    const ids = ["a", "b", "c"];
    expect(sameOrder(ids, moveItem(ids, "a", "b", "before"))).toBe(true);
    expect(sameOrder(ids, moveItem(ids, "a", "b", "after"))).toBe(false);
  });
});

describe("保存中的顺序（积压小问题 B1）", () => {
  const thread = (id: string) => ({ id });

  it("刷新带回旧顺序时仍按保存中的顺序；新会话放最前", () => {
    const fromServer = [thread("a"), thread("b"), thread("new"), thread("c")];
    expect(pendingOrder(fromServer, ["c", "a", "b"]).map((t) => t.id)).toEqual([
      "new",
      "c",
      "a",
      "b",
    ]);
  });

  it("保存的顺序里有已删掉的会话：跳过它", () => {
    expect(pendingOrder([thread("a"), thread("b")], ["b", "gone", "a"]).map((t) => t.id)).toEqual([
      "b",
      "a",
    ]);
  });
});
