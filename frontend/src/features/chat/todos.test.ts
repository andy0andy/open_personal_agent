import { describe, expect, it } from "vitest";
import type { TodoItem } from "../../api/types";
import type { ChatItem } from "./reducer";
import { latestTodos, todoProgress } from "./todos";

const todos = (...statuses: TodoItem["status"][]): TodoItem[] =>
  statuses.map((status, index) => ({ content: `第 ${index + 1} 步`, status }));

describe("待办进度", () => {
  it("做完几项、一共几项、正在做哪一项", () => {
    expect(todoProgress(todos("completed", "completed", "in_progress", "pending"))).toEqual({
      done: 2,
      total: 4,
      current: "第 3 步",
    });
  });

  it("没有进行中的项：current 为空", () => {
    expect(todoProgress(todos("completed", "pending"))).toEqual({
      done: 1,
      total: 2,
      current: null,
    });
  });
});

describe("这一轮最新的待办", () => {
  const user = (id: string): ChatItem => ({ kind: "user", id, text: "做" });
  const list = (id: string, items: TodoItem[]): ChatItem => ({ kind: "todos", id, todos: items });

  it("最后一条用户消息之后最新的那份", () => {
    const items = [
      user("u1"),
      list("todos-r1", todos("pending")),
      user("u2"),
      list("todos-r2", todos("in_progress", "pending")),
    ];
    expect(latestTodos({ items, running: true })).toEqual(todos("in_progress", "pending"));
  });

  it("上一轮的待办不算", () => {
    const items = [user("u1"), list("todos-r1", todos("pending")), user("u2")];
    expect(latestTodos({ items, running: true })).toBeNull();
  });
});
