import type { TodoItem } from "../../api/types";
import type { ChatState } from "./reducer";

/** 待办进度：做完几项、一共几项、正在做哪一项（没有进行中的为空）。 */
export function todoProgress(todos: TodoItem[]): {
  done: number;
  total: number;
  current: string | null;
} {
  return {
    done: todos.filter((todo) => todo.status === "completed").length,
    total: todos.length,
    current: todos.find((todo) => todo.status === "in_progress")?.content ?? null,
  };
}

/** 这一轮（最后一条用户消息之后）最新的待办；这一轮还没有待办时为空，上一轮的不算。 */
export function latestTodos(state: ChatState): TodoItem[] | null {
  for (let index = state.items.length - 1; index >= 0; index -= 1) {
    const item = state.items[index];
    if (item?.kind === "user") return null;
    if (item?.kind === "todos") return item.todos;
  }
  return null;
}
