import { Check, ChevronUp, Circle, CircleDashed, ListTodo, LoaderCircle } from "lucide-react";
import type { TodoItem } from "../../api/types";
import { todoProgress } from "../../features/chat/todos";

/**
 * 待办清单。active：这一轮还在进行（运行中或在等审批）；结束后没做完的项写"未完成"，不再转圈。
 */
export function TodoList({ todos, active }: { todos: TodoItem[]; active: boolean }) {
  return (
    <ul className="space-y-1.5">
      {todos.map((todo, index) => {
        const done = todo.status === "completed";
        const unfinished = !done && !active;
        return (
          <li key={index} className="flex items-start gap-2">
            <span className="mt-0.5 shrink-0" aria-hidden="true">
              {done ? (
                <Check className="size-3.5 text-success" />
              ) : unfinished ? (
                <CircleDashed className="size-3.5 text-muted-foreground" />
              ) : todo.status === "in_progress" ? (
                <LoaderCircle className="size-3.5 animate-spin text-info" />
              ) : (
                <Circle className="size-3.5 text-muted-foreground" />
              )}
            </span>
            <span className={done ? "text-muted-foreground line-through" : "text-foreground"}>
              {todo.content}
              {unfinished && <span className="ml-1.5 text-xs text-muted-foreground">未完成</span>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** 输入框上方的待办进度（设计 2026-10-22 3.7）：只在这一轮进行中显示，点开看全部。 */
export function TodoBar({ todos }: { todos: TodoItem[] }) {
  const { done, total, current } = todoProgress(todos);
  return (
    <details className="group/todo mb-2 rounded-lg border border-border bg-card text-[13px]">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-muted-foreground transition-colors hover:text-foreground">
        <ListTodo aria-hidden="true" className="size-3.5 shrink-0" />
        <span className="shrink-0 tabular-nums">{`进度 ${done}/${total}`}</span>
        {current && <span className="min-w-0 truncate">{`· 正在：${current}`}</span>}
        <ChevronUp
          aria-hidden="true"
          className="ml-auto size-3.5 shrink-0 transition-transform group-open/todo:rotate-180"
        />
      </summary>
      <div className="max-h-60 overflow-y-auto border-t border-border px-3 py-2.5">
        <TodoList todos={todos} active />
      </div>
    </details>
  );
}
