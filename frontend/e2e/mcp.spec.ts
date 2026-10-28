import { expect, test, type Page } from "@playwright/test";

// 后端是 backend/tests/e2e_server.py：临时 .workdata 里有服务 demo（三个工具，demo_list_notes、demo_wait 声明只读）。
// 所有用例共用一个临时 workdata：改过的状态用例结束前恢复。
const mine = (page: Page) => page.getByRole("region", { name: "我的 MCP 服务" });
const row = (page: Page, name: string) =>
  mine(page)
    .getByRole("listitem")
    .filter({ has: page.getByText(name, { exact: true }) });

test("我的服务：状态与开关，刷新后还在", async ({ page }) => {
  await page.goto("/chat");
  await page.locator("aside").getByRole("link", { name: "MCP" }).click();
  await expect(page).toHaveURL(/\/mcp$/);
  await expect(page.getByText(/预览：/)).toHaveCount(0);
  await expect(row(page, "demo")).toContainText("已连接");
  await expect(row(page, "demo")).toContainText("3 个工具");
  await expect(row(page, "demo")).not.toContainText("自带"); // 不再有"自带"（D22）
  await row(page, "demo").getByRole("switch", { name: "启用 demo" }).click();
  await expect(row(page, "demo")).toContainText("已停用");
  await page.reload();
  await expect(row(page, "demo")).toContainText("已停用");
  await row(page, "demo").getByRole("switch", { name: "启用 demo" }).click();
  await expect(row(page, "demo")).toContainText("已连接");
});

test("手动添加需要密钥的服务：列表说明缺哪个环境变量", async ({ page }) => {
  await page.goto("/mcp");
  await page.getByRole("button", { name: "手动添加" }).click();
  const drawer = page.getByRole("dialog", { name: "手动添加 MCP 服务" });
  await drawer.getByRole("tab", { name: "粘贴 JSON" }).click();
  await drawer.getByLabel("配置 JSON").fill(
    JSON.stringify({
      mcpServers: { brave: { command: "npx", env: { BRAVE_API_KEY: "${E2E_NOT_SET_KEY}" } } },
    }),
  );
  await drawer.getByRole("button", { name: "保存并连接" }).click();
  await expect(row(page, "brave")).toContainText("缺少环境变量：E2E_NOT_SET_KEY");
  await row(page, "brave").getByRole("button", { name: "编辑" }).click();
  await page
    .getByRole("dialog", { name: "编辑 brave" })
    .getByRole("button", { name: "删除" })
    .click();
  await page.getByRole("alertdialog").getByRole("button", { name: "删除" }).click();
  await expect(row(page, "brave")).toHaveCount(0);
});

test("粘贴 JSON：识别后又改了文字，保存的是现在的内容；用户加的可以删除", async ({ page }) => {
  await page.goto("/mcp");
  await page.getByRole("button", { name: "手动添加" }).click();
  const drawer = page.getByRole("dialog", { name: "手动添加 MCP 服务" });
  await drawer.getByRole("tab", { name: "粘贴 JSON" }).click();
  const box = drawer.getByLabel("配置 JSON");
  await box.fill(JSON.stringify({ mcpServers: { demo: { command: "npx" } } }));
  await drawer.getByRole("button", { name: "识别" }).click();
  await expect(drawer).toContainText("识别到 1 个服务");
  await drawer.getByRole("button", { name: "保存并连接" }).click();
  await expect(drawer).toContainText("已有同名服务：demo");
  await box.fill(
    JSON.stringify({
      mcpServers: { memo: { command: "npx", args: ["memo-mcp"] }, wiki: { url: "https://w/mcp" } },
    }),
  );
  await drawer.getByRole("button", { name: "保存并连接" }).click();
  await expect(row(page, "memo")).toBeVisible();
  await expect(row(page, "wiki")).toContainText("网络");
  for (const name of ["memo", "wiki"]) {
    await row(page, name).getByRole("button", { name: "编辑" }).click();
    const edit = page.getByRole("dialog", { name: `编辑 ${name}` });
    await edit.getByRole("button", { name: "删除" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "删除" }).click();
    await expect(row(page, name)).toHaveCount(0);
  }
});

test("编辑时服务名不能改；任何服务都能删（D22）", async ({ page }) => {
  await page.goto("/mcp");
  await row(page, "demo").getByRole("button", { name: "编辑" }).click();
  const drawer = page.getByRole("dialog", { name: "编辑 demo" });
  await expect(drawer.getByLabel("服务名")).toBeDisabled();
  await expect(drawer.getByRole("button", { name: "删除" })).toBeVisible();
});

test("按工具设置审批，刷新后还在", async ({ page }) => {
  await page.goto("/mcp");
  await row(page, "demo").getByRole("button", { name: "查看工具" }).click();
  const drawer = page.getByRole("dialog", { name: "demo 的工具" });
  const listNotes = drawer.getByRole("listitem").filter({ hasText: "demo_list_notes" });
  await expect(listNotes).toContainText("只读");
  const addNote = drawer.getByRole("listitem").filter({ hasText: "demo_add_note" });
  await expect(addNote.getByRole("button", { name: "先问" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await addNote.getByRole("button", { name: "自动" }).click();
  await expect(addNote.getByRole("button", { name: "自动" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.reload();
  await row(page, "demo").getByRole("button", { name: "查看工具" }).click();
  const again = page
    .getByRole("dialog", { name: "demo 的工具" })
    .getByRole("listitem")
    .filter({ hasText: "demo_add_note" });
  await expect(again.getByRole("button", { name: "自动" })).toHaveAttribute("aria-pressed", "true");
  await again.getByRole("button", { name: "先问" }).click();
  await expect(again.getByRole("button", { name: "先问" })).toHaveAttribute("aria-pressed", "true");
});
