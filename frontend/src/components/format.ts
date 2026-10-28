const UNITS = ["KB", "MB", "GB"];

/** 文件大小：不足 1KB 显示字节数，否则换算成 KB / MB / GB，保留一位小数。 */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${UNITS[unit]}`;
}

/** 路径里的文件名（最后一段）。 */
export function fileName(path: string): string {
  return path.split("/").at(-1) ?? path;
}
