import { expect, test } from "@playwright/test";
import { newThread, send } from "./helpers";

test("只显示输入、输出两个数：不显示费用，也不单列缓存（设计 2026-10-19 4.11）", async ({
  page,
}) => {
  await newThread(page);
  await send(page, "打招呼");
  await expect(page.getByText("你好，我是测试助手")).toBeVisible();
  await expect(page.getByText(/输入 100/).first()).toBeVisible();
  await expect(page.locator("body")).not.toContainText("$");
  await expect(page.locator("body")).not.toContainText("缓存");

  await page.locator("aside").getByRole("link", { name: "用量" }).click();
  await expect(page.getByText("调用次数")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("$");
  await expect(page.locator("body")).not.toContainText("费用");
  await expect(page.getByRole("columnheader", { name: "缓存读" })).toHaveCount(0);

  await page.locator("aside").getByRole("link", { name: "设置" }).click();
  await expect(page.getByText("默认对话模型")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("预算"); // 预算刹车已去掉（D23）
  await expect(page.locator("body")).not.toContainText("$");
  await expect(page.locator("body")).not.toContainText("美元");
});
