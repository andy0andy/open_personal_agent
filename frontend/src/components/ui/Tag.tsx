import type { ReactNode } from "react";

const TONES = {
  default: "bg-accent text-foreground",
  // 默认模型这类"选定的那一个"
  solid: "bg-primary text-primary-foreground",
  // 状态：淡底 + 正文色文字（提示色只用在圆点、图标上，设计 2026-10-22 2.1）
  warning: "bg-warning-soft text-foreground",
  success: "bg-success-soft text-foreground",
  danger: "bg-danger-soft text-foreground",
  info: "bg-info-soft text-foreground",
  // 次要信息：连接方式、"已停用"
  outline: "border border-border text-muted-foreground",
} as const;

/** 小标签：能力、类型、"默认""只读"等（6 像素圆角，设计 2026-10-22 2.3）。 */
export function Tag({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: keyof typeof TONES;
}) {
  return (
    <span
      className={`inline-flex h-[22px] items-center gap-1 rounded-md px-2 text-xs leading-none whitespace-nowrap ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}
