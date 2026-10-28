import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/** 写死颜色检查（设计文档 13.2）：组件只能用语义样式类，具体颜色只能出现在主题与令牌文件中。 */
const SRC = fileURLToPath(new URL("..", import.meta.url));
const ALLOWED_DIRS = ["themes", "styles"];
const PALETTE =
  /\b(?:bg|text|border|ring|outline|fill|stroke|from|via|to|divide|placeholder|shadow|decoration|caret)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|black|white)(?:-\d{2,3})?\b/;
const LITERAL = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/;
// 任意值写法：新式颜色函数，或颜色类后面方括号里的颜色名（如 bg-[red]）
const ARBITRARY =
  /\b(?:oklch|oklab|lab|lch|hwb)\(|\b(?:bg|text|border|ring|outline|fill|stroke|from|via|to|divide|placeholder|shadow|decoration|caret|accent)-\[[a-z]+\]/;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

function hasRawColor(line: string): boolean {
  return PALETTE.test(line) || LITERAL.test(line) || ARBITRARY.test(line);
}

describe("写死颜色检查", () => {
  it("规则本身：认得出各种写死颜色的写法，不误伤非颜色的任意值", () => {
    const raw = [
      "bg-red-500",
      "text-[#fff]",
      "bg-[red]",
      "text-[oklch(0.6_0.2_30)]",
      "border-[rgb(1,2,3)]",
      'style={{ color: "rgba(0,0,0,.5)" }}',
    ];
    const fine = ["w-[3px]", "grid-cols-[1fr_auto]", "bg-[var(--surface)]", "text-[0.7rem]"];
    expect(raw.filter((line) => !hasRawColor(line))).toEqual([]);
    expect(fine.filter(hasRawColor)).toEqual([]);
  });

  it("组件代码中没有具体颜色", () => {
    const offenders = sourceFiles(SRC)
      .filter((path) => !ALLOWED_DIRS.includes(relative(SRC, path).split(sep)[0] ?? ""))
      .flatMap((path) =>
        readFileSync(path, "utf8")
          .split("\n")
          .map((line, index) => ({ line, at: `${relative(SRC, path)}:${index + 1}` }))
          .filter(({ line }) => hasRawColor(line))
          .map(({ at, line }) => `${at}  ${line.trim()}`),
      );
    expect(offenders).toEqual([]);
  });
});
