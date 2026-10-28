import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { THEMES } from "./registry";
import type { ColorMode } from "./types";

/**
 * 看得清（设计 2026-10-22 2.1）：提示色与次要文字的对比度至少 4.5（WCAG 正文标准）。
 * 原来浅色模式的琥珀、成功色在暖白背景上只有 1.6，次要文字 3.9。
 */
const MODES: ColorMode[] = ["dark", "light"];
const CASES = THEMES.flatMap((theme) => MODES.map((mode) => [theme.name, mode, theme] as const));

function channels(hex: string): number[] {
  return [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16) / 255);
}

/** 与 CSS 的 color-mix(in srgb, a ratio, b) 相同：按比例混合两种颜色。 */
function mix(a: string, b: string, ratio: number): string {
  const [x, y] = [channels(a), channels(b)];
  return `#${x
    .map((value, index) => Math.round((value * ratio + (y[index] ?? 0) * (1 - ratio)) * 255))
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("")}`;
}

function luminance(hex: string): number {
  const [r, g, b] = channels(hex).map((value) =>
    value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * (r ?? 0) + 0.7152 * (g ?? 0) + 0.0722 * (b ?? 0);
}

function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return ((light ?? 0) + 0.05) / ((dark ?? 0) + 0.05);
}

const percent = (value: string) => Number.parseFloat(value) / 100;

describe("配色对比度", () => {
  it.each(CASES)("主题 %s 的 %s 版：提示色在背景上看得清", (_, mode, theme) => {
    const colors = theme.modes[mode];
    for (const name of ["warning", "success", "danger", "info"] as const) {
      expect(contrast(colors[name], colors.background), name).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(CASES)("主题 %s 的 %s 版：次要文字在背景、卡片、选中底色上看得清", (_, mode, theme) => {
    const { primary, background, mutedRatio } = theme.modes[mode];
    const muted = mix(primary, background, percent(mutedRatio));
    for (const [surface, ratio] of [
      ["背景", 0],
      ["卡片", 0.04],
      ["选中底色", 0.11],
    ] as const) {
      const color = mix(primary, background, ratio);
      expect(contrast(muted, color), surface).toBeGreaterThanOrEqual(4.5);
    }
  });
});

/** tokens.css 里按模式设的比例（输入框边框、焦点框不是主题字段，由背景与主色混合） */
const tokensCss = readFileSync(new URL("../styles/tokens.css", import.meta.url), "utf8");
function strength(mode: ColorMode, name: string): number {
  const selector = mode === "light" ? ':root[data-mode="light"]' : ":root";
  const blocks = tokensCss.split(`${selector} {`).slice(1);
  for (const block of blocks) {
    const found = new RegExp(`--${name}:\\s*(\\d+)%`).exec(block.slice(0, block.indexOf("}")));
    if (found?.[1]) return Number(found[1]) / 100;
  }
  throw new Error(`tokens.css 里没有 ${selector} 的 --${name}`);
}

describe("输入框边框与焦点框看得清（积压小问题 H3：不低于 3:1）", () => {
  it.each(CASES)("主题 %s 的 %s 版", (_, mode, theme) => {
    const { primary, background } = theme.modes[mode];
    for (const name of ["input-strength", "ring-strength"]) {
      const color = mix(primary, background, strength(mode, name));
      for (const [surface, ratio] of [
        ["背景", 0],
        ["卡片", 0.04],
      ] as const) {
        expect(
          contrast(color, mix(primary, background, ratio)),
          `${name} 在${surface}上`,
        ).toBeGreaterThanOrEqual(3);
      }
    }
  });
});
