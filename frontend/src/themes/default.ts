import type { ThemeDefinition } from "./types";

/** 默认主题：深色科技感，参考 Hermes Agent 的 "Hermes Teal"。 */
export const defaultTheme: ThemeDefinition = {
  name: "default",
  label: "默认",
  modes: {
    dark: {
      background: "#041c1c",
      primary: "#ffe6cb",
      danger: "#ff5a5f",
      success: "#4ade80",
      warning: "#ffbd38",
      info: "#6aa7f0",
      mutedRatio: "62%",
      softRatio: "10%",
    },
    // 浅色的提示色更深、次要文字更深、淡底更浅：在暖白背景上对比度都不低于 4.5
    light: {
      background: "#fbf7f0",
      primary: "#0b3b3a",
      danger: "#b42318",
      success: "#1f7a4d",
      warning: "#b45309",
      info: "#1d5fa8",
      mutedRatio: "76%",
      softRatio: "7%",
    },
  },
  typography: {
    fontSans: 'system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    fontMono: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
    baseSize: "15px",
    lineHeight: "1.55",
  },
  layout: { radius: "0.5rem", density: "comfortable" },
};
