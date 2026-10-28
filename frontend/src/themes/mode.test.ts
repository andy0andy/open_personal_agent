import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { loadPreference, MODE_STORAGE_KEY, resolveMode, savePreference } from "./mode";

describe("深浅色偏好", () => {
  it("跟随系统时按系统设置决定，固定时忽略系统设置", () => {
    expect(resolveMode("system", true)).toBe("dark");
    expect(resolveMode("system", false)).toBe("light");
    expect(resolveMode("light", true)).toBe("light");
  });

  it("读取保存过的选择；无效值、没有存储或存储报错时退回跟随系统", () => {
    const saved = new Map<string, string>();
    const storage = {
      getItem: (key: string) => saved.get(key) ?? null,
      setItem: (key: string, value: string) => void saved.set(key, value),
    };
    savePreference(storage, "light");
    expect(saved.get(MODE_STORAGE_KEY)).toBe("light");
    expect(loadPreference(storage)).toBe("light");

    saved.set(MODE_STORAGE_KEY, "purple");
    expect(loadPreference(storage)).toBe("system");
    expect(loadPreference(null)).toBe("system");
    expect(
      loadPreference({
        getItem: () => {
          throw new Error("SecurityError");
        },
      }),
    ).toBe("system");
  });
});

describe("首屏不闪烁", () => {
  it("index.html 的内联脚本读取同一个存储键（改名时两处要一起改）", () => {
    const html = readFileSync(new URL("../../index.html", import.meta.url), "utf8");
    expect(html).toContain(`localStorage.getItem("${MODE_STORAGE_KEY}")`);
  });
});
