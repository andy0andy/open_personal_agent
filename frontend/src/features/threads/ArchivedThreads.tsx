import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { archivedThreadsQuery } from "../../api/queries";
import { StatusDot } from "../../components/ui/StatusDot";
import type { Thread } from "../../api/types";
import { archivedLabel, threadActivity } from "./activity";

/** 归档的会话同样显示状态点（如"有新回答"）：没有状态时留出同样宽的空位，标题对齐 */
function ActivityDot({ thread }: { thread: Thread }) {
  const activity = threadActivity(thread);
  return activity ? (
    <StatusDot tone={activity.tone} pulse={activity.pulse} />
  ) : (
    <span aria-hidden="true" className="size-2 shrink-0" />
  );
}

/** 归档的会话（设计 2026-10-23 6.5）：在会话列表底部折叠着，点开可以打开、在顶栏里取消归档。 */
export function ArchivedThreads({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (threadId: string) => void;
}) {
  const archived = useQuery(archivedThreadsQuery);
  const [open, setOpen] = useState(false);
  const threads = archived.data ?? [];
  const label = archivedLabel(threads.length);
  if (!label) return null;
  return (
    <div className="border-t border-border pt-2">
      <button
        type="button"
        aria-expanded={open}
        className="flex w-full items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
        onClick={() => setOpen((value) => !value)}
      >
        <ChevronRight
          className={`size-3.5 transition-transform ${open ? "rotate-90" : ""}`}
          aria-hidden="true"
        />
        {label}
      </button>
      {open && (
        <ul className="max-h-48 overflow-y-auto">
          {threads.map((thread) => (
            <li key={thread.id}>
              <button
                type="button"
                className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-muted-foreground hover:bg-muted ${
                  thread.id === selectedId ? "bg-muted text-foreground" : ""
                }`}
                onClick={() => onSelect(thread.id)}
              >
                <ActivityDot thread={thread} />
                <span className="min-w-0 flex-1 truncate">{thread.title || "新会话"}</span>
                {threadActivity(thread) && (
                  <span className="shrink-0 text-xs">{threadActivity(thread)?.label}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
