import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { themeVariables } from "./apply";
import { DEFAULT_THEME, THEMES } from "./registry";
import type { ColorMode } from "./types";

const HEX = /^#[0-9a-f]{6}$/i;
const PERCENT = /^\d{1,3}%$/;
const MODES: ColorMode[] = ["dark", "light"];
const tokensCss = readFileSync(new URL("../styles/tokens.css", import.meta.url), "utf8");

function cssBlock(selector: string): string {
  const start = tokensCss.indexOf(`${selector} {`);
  return tokensCss.slice(start, tokensCss.indexOf("}", start));
}

function declared(block: string): Record<string, string> {
  return Object.fromEntries(
    [...block.matchAll(/(--theme-[a-z-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2]?.trim() ?? ""]),
  );
}

describe("主题契约", () => {
  it.each(THEMES.map((theme) => [theme.name, theme] as const))(
    "主题 %s 的深浅两版都提供合法的颜色与比例",
    (_, theme) => {
      for (const mode of MODES) {
        const { mutedRatio, softRatio, ...colors } = theme.modes[mode];
        for (const [name, color] of Object.entries(colors)) expect(color, name).toMatch(HEX);
        expect(mutedRatio).toMatch(PERCENT);
        expect(softRatio).toMatch(PERCENT);
      }
      expect(theme.typography.fontSans).not.toBe("");
      expect(theme.typography.fontMono).not.toBe("");
    },
  );

  it("主题变量与 tokens.css 中声明的变量一一对应", () => {
    const names = Object.keys(declared(cssBlock(":root"))).sort();
    for (const theme of THEMES) {
      expect(Object.keys(themeVariables(theme, "dark")).sort()).toEqual(names);
    }
  });

  it("tokens.css 的首屏默认值与默认主题一致（脚本运行前不闪烁）", () => {
    const dark = themeVariables(DEFAULT_THEME, "dark");
    const light = themeVariables(DEFAULT_THEME, "light");
    expect(declared(cssBlock(":root"))).toEqual(dark);
    // 浅色块只写随模式变化的变量（提示色、比例也按模式设定，设计 2026-10-22 2.1）
    const changed = Object.fromEntries(
      Object.entries(light).filter(([name, value]) => dark[name] !== value),
    );
    expect(declared(cssBlock(':root[data-mode="light"]'))).toEqual(changed);
  });
});
