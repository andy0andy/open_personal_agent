import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/**
 * 测试不靠固定等待保证先后顺序（设计 2026-10-23 7.6）：setTimeout 等非 0 毫秒的改用假时钟
 * （vi.useFakeTimers）或等条件（vi.waitFor）；替身里模拟慢的在这次调用跨过的某一行注明"允许等待：原因"。
 */
const SRC = fileURLToPath(new URL(".", import.meta.url));
const WAITS_MS = /,\s*[1-9]\d*\s*,?\s*\)$/;
const ALLOWED = "允许等待：";

function testFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return testFiles(path);
    return /\.test\.tsx?$/.test(name) && name !== "test-hygiene.test.ts" ? [path] : [];
  });
}

/** 从开括号起按括号配对，返回配对的右括号之后的位置；没配上时为 -1。 */
function closingParen(text: string, open: number): number {
  let depth = 0;
  for (let index = open; index < text.length; index += 1) {
    if (text[index] === "(") depth += 1;
    if (text[index] === ")") depth -= 1;
    if (depth === 0) return index + 1;
  }
  return -1;
}

/**
 * 不注明理由的固定等待在第几行：每个 setTimeout(…) 按括号配对找到整次调用（跨行写的也算，
 * 积压小问题 I17），结尾是"，非 0 毫秒)"就算；这次调用跨过的任何一行写了"允许等待："就放过。
 */
function fixedWaitLines(text: string): number[] {
  const found: number[] = [];
  const name = "setTimeout(";
  for (let start = text.indexOf(name); start !== -1; start = text.indexOf(name, start + 1)) {
    const end = closingParen(text, start + name.length - 1);
    if (end === -1 || !WAITS_MS.test(text.slice(start, end))) continue;
    const lineEnd = text.indexOf("\n", end);
    const lines = text.slice(
      text.lastIndexOf("\n", start) + 1,
      lineEnd === -1 ? undefined : lineEnd,
    );
    if (!lines.includes(ALLOWED)) found.push(text.slice(0, start).split("\n").length);
  }
  return found;
}

describe("测试不靠固定等待", () => {
  it("规则本身：认得出等非 0 毫秒的写法，放过等 0 毫秒的", () => {
    expect(fixedWaitLines("await new Promise((resolve) => setTimeout(resolve, 10));")).toEqual([1]);
    expect(fixedWaitLines('setTimeout(() => resolve([thread("old")]), 20)')).toEqual([1]);
    expect(fixedWaitLines("await new Promise((resolve) => setTimeout(resolve, 0));")).toEqual([]);
  });

  it("规则本身：跨行写的也认得出，注明理由的放过（积压小问题 I17）", () => {
    // prettier 把放不下一行的调用逐个参数换行时，最后一个参数后面带逗号
    expect(fixedWaitLines("setTimeout(\n  resolve,\n  50,\n);\n")).toEqual([1]);
    expect(fixedWaitLines("setTimeout(\n  resolve,\n  0,\n);\n")).toEqual([]);
    expect(fixedWaitLines("x();\nsetTimeout(() => {\n  done();\n}, 50);\n")).toEqual([2]);
    expect(fixedWaitLines("setTimeout(() => {\n  done();\n}, 0);\n")).toEqual([]);
    expect(fixedWaitLines("setTimeout(() => {\n  done();\n}, 50); // 允许等待：模拟慢\n")).toEqual(
      [],
    );
  });

  it("测试文件里没有不注明理由的固定等待", () => {
    const found = testFiles(SRC).flatMap((file) =>
      fixedWaitLines(readFileSync(file, "utf8")).map((line) => `${relative(SRC, file)}:${line}`),
    );
    expect(found).toEqual([]);
  });
});
