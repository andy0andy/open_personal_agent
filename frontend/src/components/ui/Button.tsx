import type { ComponentProps } from "react";

type Variant = "outline" | "primary" | "danger" | "ghost";

const VARIANTS: Record<Variant, string> = {
  // 次按钮：输入框边框 + 透明底
  outline: "border-input text-foreground hover:bg-muted",
  // 主按钮：正文色实心，每页最多一个
  primary: "border-primary bg-primary text-primary-foreground hover:opacity-90",
  // 危险操作：危险色文字
  danger: "border-transparent text-danger hover:bg-danger-soft",
  // 文字按钮
  ghost: "border-transparent text-muted-foreground hover:bg-muted hover:text-foreground",
};

/** 按钮三级（设计 2026-10-22 2.3）：8 像素圆角、句子写法，不用等宽大写。 */
export function Button({
  variant = "outline",
  className = "",
  type = "button",
  ...props
}: ComponentProps<"button"> & { variant?: Variant }) {
  return (
    <button
      type={type}
      className={`inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border px-3 text-[13px] leading-none whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}
