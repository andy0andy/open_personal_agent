import type { ColorMode, ThemeDefinition } from "./types";

/** 主题在某个模式下对应的 CSS 变量；名字必须与 styles/tokens.css 里 :root 声明的一致。 */
export function themeVariables(theme: ThemeDefinition, mode: ColorMode): Record<string, string> {
  const colors = theme.modes[mode];
  return {
    "--theme-background": colors.background,
    "--theme-primary": colors.primary,
    "--theme-danger": colors.danger,
    "--theme-success": colors.success,
    "--theme-warning": colors.warning,
    "--theme-info": colors.info,
    "--theme-muted-ratio": colors.mutedRatio,
    "--theme-soft-ratio": colors.softRatio,
    "--theme-font-sans": theme.typography.fontSans,
    "--theme-font-mono": theme.typography.fontMono,
    "--theme-base-size": theme.typography.baseSize,
    "--theme-line-height": theme.typography.lineHeight,
    "--theme-radius": theme.layout.radius,
    "--theme-spacing": theme.layout.density === "compact" ? "0.22rem" : "0.25rem",
  };
}

/** 把主题写到根节点上：data-theme / data-mode 属性 + CSS 变量。 */
export function applyTheme(root: HTMLElement, theme: ThemeDefinition, mode: ColorMode): void {
  root.dataset.theme = theme.name;
  root.dataset.mode = mode;
  root.style.colorScheme = mode;
  for (const [name, value] of Object.entries(themeVariables(theme, mode))) {
    root.style.setProperty(name, value);
  }
}
