import type { ColorMode } from "./types";

export type ModePreference = "system" | ColorMode;

/** 与 index.html 中的内联脚本使用同一个键。 */
export const MODE_STORAGE_KEY = "opa.color-mode";

const PREFERENCES: readonly ModePreference[] = ["system", "dark", "light"];

export function resolveMode(preference: ModePreference, prefersDark: boolean): ColorMode {
  if (preference !== "system") return preference;
  return prefersDark ? "dark" : "light";
}

/** 读取用户选择；浏览器禁用本地存储或值无效时退回"跟随系统"。 */
export function loadPreference(storage: Pick<Storage, "getItem"> | null): ModePreference {
  try {
    const value = storage?.getItem(MODE_STORAGE_KEY);
    return PREFERENCES.find((preference) => preference === value) ?? "system";
  } catch {
    return "system";
  }
}

export function savePreference(
  storage: Pick<Storage, "setItem"> | null,
  preference: ModePreference,
): void {
  try {
    storage?.setItem(MODE_STORAGE_KEY, preference);
  } catch {
    // 本地存储不可用时只在本次会话生效
  }
}

export function browserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}
