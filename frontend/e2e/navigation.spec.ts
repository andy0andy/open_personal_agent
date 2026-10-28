import { expect, test } from "@playwright/test";
import { newThread, send, tokenHeaders } from "./helpers";

const EMPTY = "今天想做点什么？";

test("侧栏各页有自己的地址，刷新后回到原页", async ({ page }) => {
  await page.goto("/chat");
  for (const [label, path] of [
    ["知识库", "/knowledge"],
    ["用量", "/usage"],
    ["设置", "/settings"],
  ] as const) {
    await page.locator("aside").getByRole("link", { name: label }).click();
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: label })).toBeVisible();
  }
});

test("去别的页再点\u201c对话\u201d，回到刚才的会话", async ({ page }) => {
  await newThread(page);
  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/);
  const url = page.url();
  await page.locator("aside").getByRole("link", { name: "用量" }).click();
  await expect(page).toHaveURL(/\/usage$/);
  await page.locator("aside").getByRole("link", { name: "对话" }).click();
  await expect(page).toHaveURL(url);
});

test("首页与未知地址回到对话页", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/chat$/);
  await page.goto("/nope");
  await expect(page).toHaveURL(/\/chat$/);
});

test("对话页地址带会话 ID，刷新回到同一会话", async ({ page }) => {
  await newThread(page);
  await send(page, "打招呼");
  await expect(page.getByText("你好，我是测试助手")).toBeVisible();
  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/);
  await page.reload();
  await expect(page.getByText("你好，我是测试助手")).toBeVisible();
});

test("会话被删后回到空状态", async ({ page }) => {
  await newThread(page);
  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/);
  const url = page.url();
  const threadId = url.split("/").pop() ?? "";
  const headers = await tokenHeaders(page);
  expect((await page.request.delete(`/api/threads/${threadId}`, { headers })).ok()).toBe(true);
  await page.goto(url);
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.getByText(EMPTY)).toBeVisible();
});

test("会话栏可以收起", async ({ page }) => {
  await page.goto("/chat");
  const list = page.getByRole("navigation", { name: "会话列表" });
  await expect(list).toBeVisible();
  await page.getByRole("button", { name: "收起会话列表" }).click();
  await expect(list).toBeHidden();
  await expect(page.getByRole("button", { name: "展开会话列表" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "展开会话列表" })).toBeVisible();
  await page.getByRole("button", { name: "展开会话列表" }).click();
  await expect(list).toBeVisible();
});

test("落地页直接发消息：建会话、打开它，回答照常出现", async ({ page }) => {
  await page.goto("/chat");
  const box = page.getByLabel("新会话的第一条消息");
  await box.fill("落地页打招呼"); // 剧本按关键词"打招呼"回答；标题独一份，好在列表里找
  await box.press("Enter");
  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/);
  await expect(page.getByText("你好，我是测试助手")).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "会话列表" }).getByText("落地页打招呼", { exact: true }),
  ).toBeVisible();
});
