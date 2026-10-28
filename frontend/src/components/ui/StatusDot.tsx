const TONES = {
  warning: "bg-warning",
  info: "bg-info",
  danger: "bg-danger",
  success: "bg-success",
  idle: "border-[1.5px] border-muted-foreground",
} as const;

/**
 * 状态点（设计 2026-10-22 2.1）：琥珀 = 等你处理，蓝 = 运行中，红 = 出错，绿 = 完成 / 已连接，
 * 空心 = 停用。旁边没有文字时传 label，读屏才读得出状态。
 */
export function StatusDot({
  tone,
  pulse = false,
  label,
}: {
  tone: keyof typeof TONES;
  pulse?: boolean;
  label?: string;
}) {
  const className = `inline-block size-2 shrink-0 rounded-full ${TONES[tone]} ${
    pulse ? "animate-pulse" : ""
  }`;
  return label ? (
    <span role="img" aria-label={label} title={label} className={className} />
  ) : (
    <span aria-hidden="true" className={className} />
  );
}
