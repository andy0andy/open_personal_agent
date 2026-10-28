import type { ReactNode } from "react";

/** 页头（设计 2026-10-22 2.3）：60 像素高，左边标题 + 下一行说明，右边操作。 */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex h-15 shrink-0 items-center justify-between gap-4 border-b border-border px-6">
      <div className="min-w-0">
        <h1 className="truncate text-[17px] leading-tight font-semibold">{title}</h1>
        {subtitle && <p className="truncate text-xs text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  );
}
