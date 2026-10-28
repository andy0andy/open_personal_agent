import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { newThread, openThread, send } from "./helpers";

test("回答逐字出现，刷新后还在", async ({ page }) => {
  await newThread(page);
  await send(page, "打招呼");
  await expect(page.getByText("你好，我是测试助手")).toBeVisible();
  await page.reload();
  await openThread(page, "打招呼");
  await expect(page.getByText("你好，我是测试助手")).toBeVisible();
});

test("工具行：中文名，结束后不再转圈", async ({ page }) => {
  await newThread(page);
  await send(page, "看看目录");
  await expect(page.getByText("目录看完了")).toBeVisible();
  const line = page.locator("details", { hasText: "列出目录" }).first();
  await expect(line).toBeVisible();
  await expect(line.locator("summary")).not.toContainText("运行中");
});

test("下载产物", async ({ page }) => {
  await newThread(page);
  await send(page, "写报告");
  await expect(page.getByText("报告写好了")).toBeVisible();
  await expect(page.getByRole("button", { name: "report.md" })).toBeVisible();
  // 跑完以后文件面板里已经有它（积压小问题 D2：不靠 file.created 那一下刷新）
  await page.getByRole("button", { name: "文件", exact: true }).click();
  await expect(
    page.locator("aside", { hasText: "文件" }).getByText("report.md").first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "文件", exact: true }).click();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "下载" }).first().click(),
  ]);
  const path = await download.path();
  expect(await readFile(path, "utf-8")).toContain("本周完成端到端测试");
});

test("运行中刷新页面，回答接着出完", async ({ page }) => {
  await newThread(page);
  await send(page, "慢慢说");
  await expect(page.getByText("一二三", { exact: false }).first()).toBeVisible();
  await page.reload();
  await openThread(page, "慢慢说");
  await expect(page.getByText("一二三四五六七八九十".repeat(5))).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/耗时/).first()).toBeVisible();
});

test("停止", async ({ page }) => {
  await newThread(page);
  await send(page, "慢慢说");
  await expect(page.getByText("一二", { exact: false }).first()).toBeVisible();
  await page.getByRole("button", { name: "停止" }).click();
  await expect(page.getByText("已停止", { exact: true }).first()).toBeVisible();
});

test("失败后重试这一轮：失败的那一轮收成一行", async ({ page }) => {
  await newThread(page);
  await send(page, "模拟失败");
  await expect(page.getByText("RuntimeError: 模拟的网关出错")).toBeVisible();
  // 只有报错、没有正文的那一轮不放复制按钮（积压小问题 A10）：页面上只剩用户那句话自己的复制按钮
  await expect(page.getByRole("button", { name: "复制", exact: true })).toHaveCount(1);
  await page.getByRole("button", { name: "重试这一轮" }).click();
  await expect(page.getByText("重试成功了")).toBeVisible();
  const collapsed = page.getByText("第 1 次失败：RuntimeError: 模拟的网关出错（已重试）");
  await expect(collapsed).toBeVisible();
  await expect(page.getByRole("button", { name: "重试这一轮" })).toHaveCount(0);
  await page.reload();
  await openThread(page, "模拟失败");
  await expect(collapsed).toBeVisible();
  await expect(page.getByText("重试成功了")).toBeVisible();
});

test("换的模型存在会话上：刷新后不变", async ({ page }) => {
  await newThread(page);
  const select = page.getByLabel("会话的模型");
  const saved = page.waitForResponse(
    (resp) => resp.request().method() === "PATCH" && resp.url().includes("/api/threads/"),
  );
  await select.selectOption("fake-model-2");
  expect((await saved).ok()).toBe(true);
  await page.reload();
  await expect(page.getByLabel("会话的模型")).toHaveValue("fake-model-2");
});

test("草稿：切到别的会话再回来，输入框里还是原文", async ({ page }) => {
  await newThread(page);
  const input = page.getByPlaceholder("给智能体发消息…");
  await input.fill("写了一半的话");
  await page.getByRole("button", { name: "新建会话" }).click();
  await expect(input).toHaveValue("");
  await page.goBack();
  await expect(input).toHaveValue("写了一半的话");
});
