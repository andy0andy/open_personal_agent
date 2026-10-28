import { expect, test, type Page } from "@playwright/test";

// 后端是 backend/tests/e2e_server.py：临时 .workdata/skills/ 里有 excel，上传的也写进这里。
// 所有用例共用一个临时 workdata：改过的状态用例结束前恢复。
const row = (page: Page, name: string) =>
  page.getByRole("listitem").filter({ has: page.getByText(name, { exact: true }) });
const skillMd = (name: string) => ({
  name: "SKILL.md",
  mimeType: "text/markdown",
  buffer: Buffer.from(`---\nname: ${name}\ndescription: 整理会议记录\n---\n\n# 怎么整理\n`),
});

test("excel 技能：开关刷新后还在，查看能看到正文，能删（D22）", async ({ page }) => {
  await page.goto("/chat");
  await page.locator("aside").getByRole("link", { name: "技能" }).click();
  await expect(page).toHaveURL(/\/skills$/);
  await expect(page.getByText(/预览：/)).toHaveCount(0);
  await expect(page.getByText("已启用 1 / 共 1")).toBeVisible();
  await row(page, "excel").getByRole("switch", { name: "启用 excel" }).click();
  await expect(page.getByText("已启用 0 / 共 1")).toBeVisible();
  await page.reload();
  await expect(page.getByText("已启用 0 / 共 1")).toBeVisible();
  await row(page, "excel").getByRole("switch", { name: "启用 excel" }).click();
  await expect(page.getByText("已启用 1 / 共 1")).toBeVisible();

  await row(page, "excel").getByRole("button", { name: "查看" }).click();
  const drawer = page.getByRole("dialog", { name: "excel" });
  await expect(drawer.getByText("先看清表头。")).toBeVisible();
  await expect(drawer).not.toContainText("自带");
  await expect(drawer.getByRole("button", { name: "删除技能" })).toBeVisible();
});

test("上传技能的对话框：焦点在里面，Tab 不跑出去，Esc 后回到按钮（积压小问题 H1）", async ({
  page,
}) => {
  await page.goto("/skills");
  const opener = page.getByRole("button", { name: "上传技能" });
  await opener.click();
  const dialog = page.getByRole("dialog", { name: "上传技能" });
  const focusInside = () =>
    page.evaluate(() =>
      Boolean(document.querySelector('[role="dialog"]')?.contains(document.activeElement)),
    );
  expect(await focusInside()).toBe(true);
  for (let i = 0; i < 8; i += 1) {
    await page.keyboard.press("Tab");
    expect(await focusInside()).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
});

test("上传 SKILL.md 后能看到、能删；同名的不能再传", async ({ page }) => {
  await page.goto("/skills");
  await page.getByRole("button", { name: "上传技能" }).click();
  const dialog = page.getByRole("dialog", { name: "上传技能" });
  await dialog.getByLabel("选择文件").setInputFiles(skillMd("会议纪要"));
  await expect(dialog).toContainText("会议纪要");
  await dialog.getByRole("button", { name: "安装" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(row(page, "会议纪要")).toBeVisible();
  await page.reload();
  await expect(row(page, "会议纪要")).toBeVisible();

  await page.getByRole("button", { name: "上传技能" }).click();
  await dialog.getByLabel("选择文件").setInputFiles(skillMd("会议纪要"));
  await expect(dialog).toContainText("已有同名技能「会议纪要」，换个名字再上传");
  await expect(dialog.getByRole("button", { name: "安装" })).toBeDisabled();
  await page.keyboard.press("Escape");

  await row(page, "会议纪要").getByRole("button", { name: "查看" }).click();
  await page
    .getByRole("dialog", { name: "会议纪要" })
    .getByRole("button", { name: "删除技能" })
    .click();
  await page.getByRole("alertdialog").getByRole("button", { name: "删除" }).click();
  await expect(row(page, "会议纪要")).toHaveCount(0);
});

test("不支持的文件", async ({ page }) => {
  await page.goto("/skills");
  await page.getByRole("button", { name: "上传技能" }).click();
  const dialog = page.getByRole("dialog", { name: "上传技能" });
  await dialog
    .getByLabel("选择文件")
    .setInputFiles({ name: "报告.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF") });
  await expect(dialog).toContainText("只能上传技能文件夹、.zip 或 SKILL.md");
  await expect(dialog.getByRole("button", { name: "安装" })).toBeDisabled();
});
