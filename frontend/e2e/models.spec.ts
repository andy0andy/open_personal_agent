import { expect, test, type Page } from "@playwright/test";
import { tokenHeaders } from "./helpers";

// 后端是 backend/tests/e2e_server.py：假网关里有 fake-model（默认对话）、fake-model-2 与
// embed-fake（默认向量），都带部署编号（D22：模型全部在网关数据库里，都能改）；
// 页面加的模型记在假网关的内存里。用例结束前恢复默认模型。
const list = (page: Page) => page.getByRole("region", { name: "已登记模型" });
const row = (page: Page, name: string) =>
  list(page)
    .getByRole("listitem")
    .filter({ has: page.getByText(name, { exact: true }) });

async function addModel(page: Page, name: string) {
  await page.getByRole("button", { name: "新增模型" }).click();
  const drawer = page.getByRole("dialog", { name: "新增模型" });
  await drawer.getByLabel("厂商模型 ID").fill(name);
  await drawer.getByLabel("模型名").fill(name);
  await drawer.getByLabel("上下文上限").fill("200000");
  await drawer.getByLabel("输出上限").fill("32000");
  return drawer;
}

test("模型都能改；默认模型标默认、不能删；向量模型只读", async ({ page }) => {
  await page.goto("/chat");
  await page.locator("aside").getByRole("link", { name: "模型" }).click();
  await expect(page).toHaveURL(/\/models$/);
  await expect(page.getByText(/预览：/)).toHaveCount(0);
  await expect(row(page, "fake-model")).not.toContainText("自带");
  await expect(row(page, "fake-model")).toContainText("默认");
  await expect(row(page, "fake-model").getByRole("button", { name: "编辑" })).toBeVisible();
  await expect(
    row(page, "fake-model").getByRole("button", { name: "删除 fake-model" }),
  ).toBeDisabled();
  await expect(row(page, "embed-fake")).toContainText("向量");
  await expect(page.getByText("换向量模型要重新向量化整个知识库")).toBeVisible();
});

test("新增模型：价格必填或免费；保存后能测试；Esc 关掉再打开是空表单", async ({ page }) => {
  await page.goto("/models");
  let drawer = await addModel(page, "glm-e2e");
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await page.getByRole("button", { name: "新增模型" }).click();
  drawer = page.getByRole("dialog", { name: "新增模型" });
  await expect(drawer.getByLabel("模型名")).toHaveValue("");
  await page.keyboard.press("Escape");

  drawer = await addModel(page, "glm-e2e");
  await drawer.getByRole("button", { name: "保存" }).click();
  await expect(drawer).toContainText("填写价格，或标为免费");
  await drawer.getByLabel("免费").check();
  await drawer.getByRole("button", { name: "保存" }).click();
  await expect(drawer).toHaveCount(0);
  await expect(row(page, "glm-e2e")).toContainText("免费");
  await row(page, "glm-e2e").getByRole("button", { name: "测试" }).click();
  await expect(row(page, "glm-e2e")).toContainText("✓ 可用");
  await page.reload();
  await expect(row(page, "glm-e2e")).toBeVisible();
});

test("默认模型刷新后还在、不能删；换回后删除先确认", async ({ page }) => {
  await page.goto("/models");
  const drawer = await addModel(page, "glm-default");
  await drawer.getByLabel("免费").check();
  await drawer.getByRole("button", { name: "保存" }).click();
  await expect(row(page, "glm-default")).toBeVisible();

  await page.getByLabel("对话模型").selectOption("glm-default");
  await expect(row(page, "glm-default")).toContainText("默认");
  await page.reload();
  await expect(page.getByLabel("对话模型")).toHaveValue("glm-default");
  await expect(
    row(page, "glm-default").getByRole("button", { name: "删除 glm-default" }),
  ).toBeDisabled();

  await page.getByLabel("对话模型").selectOption("fake-model");
  await expect(row(page, "fake-model")).toContainText("默认");
  await row(page, "glm-default").getByRole("button", { name: "删除 glm-default" }).click();
  const confirm = page.getByRole("alertdialog");
  await expect(confirm).toContainText("之后会改用默认模型 fake-model");
  await confirm.getByRole("button", { name: "删除" }).click();
  await expect(row(page, "glm-default")).toHaveCount(0);
});

test("会话开着时模型在别处被删：列表刷新后会话改用默认模型", async ({ page }) => {
  await page.goto("/models");
  const drawer = await addModel(page, "glm-gone");
  await drawer.getByLabel("免费").check();
  await drawer.getByRole("button", { name: "保存" }).click();
  await expect(row(page, "glm-gone")).toBeVisible();
  const headers = await tokenHeaders(page);
  const created = await page.request.post("/api/threads", {
    data: { model: "glm-gone" },
    headers,
  });
  const thread = (await created.json()) as { id: string };

  await page.goto(`/chat/${thread.id}`);
  const select = page.locator("select").first();
  await expect(select).toHaveValue("glm-gone");
  // 另一个标签页里删掉它（后端把在用它的会话改成默认模型）
  expect((await page.request.delete("/api/settings/models/glm-gone", { headers })).ok()).toBe(true);
  // 回到这个标签页时会话列表会重新拉取
  await page.evaluate(() => window.dispatchEvent(new Event("visibilitychange")));
  await expect(select).toHaveValue("fake-model");
});
