import { expect, test } from "@playwright/test";
import { newThread, send } from "./helpers";

test("用量页", async ({ page }) => {
  await newThread(page);
  await send(page, "打招呼");
  await expect(page.getByText("你好，我是测试助手")).toBeVisible();

  await page.locator("aside").getByRole("link", { name: "用量" }).click();
  await expect(page.getByText("调用次数")).toBeVisible();
  await expect(page.getByText("主智能体").first()).toBeVisible();
  // 悬停今天那根柱子：浮层整个在卡片里（日期那一行不被卡片边缘裁掉）
  const chart = page.getByRole("region", { name: "每天的用量" });
  await chart.getByRole("button").last().hover();
  const date = chart.locator("p", { hasText: /^\d{4}-\d{2}-\d{2}$/ });
  await expect(date).toBeVisible();
  const [dateBox, chartBox] = [await date.boundingBox(), await chart.boundingBox()];
  expect(dateBox && chartBox && dateBox.y >= chartBox.y).toBe(true);
  // 会话 ID 显示前 8 位，点复制得到完整 ID（到网关后台按它筛选，docs/usage.md 第 6 节）
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  const shortId = page.getByTitle("复制完整的会话 ID").first();
  await expect(shortId).toHaveText(/^[0-9a-f]{8}$/);
  await shortId.click();
  await expect(page.getByText("已复制")).toBeVisible();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  expect(copied.startsWith((await shortId.textContent()) ?? "?")).toBe(true);
  // 点会话标题打开它（积压小问题 I10）
  await shortId.locator("xpath=../..").getByRole("button").first().click(); // 同一行的标题
  await expect(page).toHaveURL(new RegExp(`/chat/${copied}$`));
});

test("设置页：改一项设置、恢复默认；列出 .workdata 里的文件（D22）", async ({ page }) => {
  await page.goto("/chat");
  await page.locator("aside").getByRole("link", { name: "设置" }).click();
  await expect(page.getByText("默认对话模型")).toBeVisible();
  const row = page.getByRole("listitem").filter({ hasText: "每次带上的相关记忆最多几条" });
  const input = row.getByRole("spinbutton");
  await input.fill("3");
  await input.press("Enter");
  await expect(row).toContainText("已保存，重启后生效");
  await expect(row).toContainText("已改");
  await row.getByRole("button", { name: "恢复默认" }).click();
  await expect(row).not.toContainText("已保存");
  await expect(row.getByRole("spinbutton")).toHaveValue("5");
  await expect(page.getByText("审批规则与预算")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "重新加载" })).toHaveCount(0);
  await expect(page.getByText("MCP 服务清单", { exact: true })).toBeVisible();
});
