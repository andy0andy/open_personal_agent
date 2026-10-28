import { useId, type ReactNode } from "react";

/** 内容卡片：12 像素圆角，区块标题用正文字体、次要色（设计 2026-10-22 2.3）。 */
export function Panel({
  id,
  title,
  note,
  action,
  children,
}: {
  /** 页内跳转的锚点（如设置页的分节导航） */
  id?: string;
  title: string;
  note?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  const titleId = useId();
  return (
    <section
      id={id}
      aria-labelledby={titleId}
      className="scroll-mt-6 overflow-hidden rounded-xl border border-border bg-card"
    >
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <div className="flex min-w-0 items-baseline gap-2.5">
          <h2 id={titleId} className="text-[13px] font-medium text-muted-foreground">
            {title}
          </h2>
          {note && <span className="truncate text-xs text-muted-foreground">{note}</span>}
        </div>
        {action}
      </div>
      <div className="border-t border-border p-4">{children}</div>
    </section>
  );
}
