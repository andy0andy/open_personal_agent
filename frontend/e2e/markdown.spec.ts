import { expect, test } from "@playwright/test";
import { newThread, send } from "./helpers";

test("回答里的代码高亮、复制代码与数学公式", async ({ page }) => {
  await newThread(page);
  await send(page, "写公式");
  const answer = page.locator(".markdown").last();

  // 代码块：按语法着色（颜色与正文不同），标题栏显示语言名，可以一键复制
  const keyword = answer.locator(".hljs-keyword").first();
  await expect(keyword).toHaveText("def");
  const [keywordColor, textColor] = await keyword.evaluate((el) => {
    const container = el.closest(".markdown");
    return [getComputedStyle(el).color, container ? getComputedStyle(container).color : ""];
  });
  expect(textColor).not.toBe("");
  expect(keywordColor).not.toBe(textColor);
  await expect(answer.locator(".code-header")).toContainText("python");
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await answer.getByRole("button", { name: "复制代码" }).click();
  await expect(answer.getByText("已复制")).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("def area(r):");

  // 公式：\(…\) 与 \[…\] 都渲染成公式（KaTeX 样式已加载），金额照常是文字
  await expect(answer.locator(".katex")).toHaveCount(2);
  await expect(answer.locator(".katex-display")).toHaveCount(1);
  await expect(answer.locator(".katex").first()).toHaveCSS("font-family", /KaTeX_Main/);
  await expect(answer).toContainText("价格 $5 到 $10");
});
