/** 主题即数据：组件只用语义样式类，具体取值都来自这里（设计文档 13.2）。 */

export type ColorMode = "dark" | "light";

/**
 * 一种深浅模式下的颜色。其余颜色由背景与主色按比例混合派生（见 styles/tokens.css）。
 * 提示色也按模式设定：为深色背景挑的颜色放到浅色背景上看不清（设计 2026-10-22 2.1）。
 */
export interface ModeColors {
  /** 背景色。 */
  background: string;
  /** 主色：正文文字、主按钮。 */
  primary: string;
  /** 出错、放宽审批。 */
  danger: string;
  /** 完成、已连接。 */
  success: string;
  /** 等你处理、品牌图标。 */
  warning: string;
  /** 运行中。 */
  info: string;
  /** 次要文字：主色混入背景的比例（如 "62%"）。 */
  mutedRatio: string;
  /** 提示色淡底：提示色混入背景的比例（如 "10%"）。 */
  softRatio: string;
}

export interface ThemeDefinition {
  name: string;
  label: string;
  modes: Record<ColorMode, ModeColors>;
  typography: { fontSans: string; fontMono: string; baseSize: string; lineHeight: string };
  layout: { radius: string; density: "compact" | "comfortable" };
}
