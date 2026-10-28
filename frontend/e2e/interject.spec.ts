import { expect, test } from "@playwright/test";
import { newThread, openThread, send } from "./helpers";

// 运行中插话（设计 2026-10-23 6.3）：剧本见 backend/tests/e2e_server.py（"等一会儿"会调一个跑 2 秒的工具）

test("工具跑着时插话：先显示已排队，下一步开始前送达，留在这一轮里", async ({ page }) => {
  await newThread(page);
  await send(page, "等一会儿再回答");
  await expect(page.getByText("demo · wait")).toBeVisible();
  const box = page.getByPlaceholder(/回车插话/);
  await box.fill("改成英文");
  await box.press("Enter");
  await expect(box).toHaveValue("");
  await expect(page.getByText(/已排队/)).toBeVisible();
  await expect(page.getByText("OK, switching to English")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("运行中插话")).toBeVisible();
  await expect(page.getByText(/已排队/)).toHaveCount(0);
  await expect(page.getByText("1 轮")).toBeVisible(); // 插话不算新的一轮
  await page.reload();
  await openThread(page, "等一会儿再回答");
  await expect(page.getByText("改成英文", { exact: true })).toBeVisible();
  await expect(page.getByText("OK, switching to English")).toBeVisible();
});

test("回答快写完时插话：没赶上这一轮的话，接着发起下一轮", async ({ page }) => {
  await newThread(page);
  await send(page, "慢慢说");
  await expect(page.getByText("一二三", { exact: false }).first()).toBeVisible();
  const box = page.getByPlaceholder(/回车插话/);
  await box.fill("顺便打招呼");
  await box.press("Enter");
  await expect(page.getByText("你好，我是测试助手")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("2 轮")).toBeVisible();
});

test("插了话又点停止：没送达的话放回输入框", async ({ page }) => {
  await newThread(page);
  await send(page, "慢慢说");
  await expect(page.getByText("一二三", { exact: false }).first()).toBeVisible();
  const box = page.getByPlaceholder(/回车插话/);
  await box.fill("换个说法");
  await box.press("Enter");
  await expect(page.getByText(/已排队/)).toBeVisible();
  await page.getByRole("button", { name: "停止" }).click();
  await expect(page.getByText("插话没送达，已放回输入框")).toBeVisible();
  await expect(page.getByPlaceholder("给智能体发消息…")).toHaveValue("换个说法");
});
