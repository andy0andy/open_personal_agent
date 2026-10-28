import { defaultTheme } from "./default";
import type { ThemeDefinition } from "./types";

/** 主题登记表：新增主题 = 新增一个主题文件 + 在这里登记一行，组件不用改。 */
export const THEMES: readonly ThemeDefinition[] = [defaultTheme];

export const DEFAULT_THEME = defaultTheme;
