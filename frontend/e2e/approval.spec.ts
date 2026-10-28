import { expect, test } from "@playwright/test";
import { newThread, send } from "./helpers";

test("审批：同意后接着做完", async ({ page }) => {
  await newThread(page);
  await send(page, "记笔记");
  await expect(page.getByText("要调用 demo · add_note 吗？")).toBeVisible();
  // 卡片不抢输入框的焦点：正在打字时一个空格或回车不能变成"同意"
  const composer = page.getByPlaceholder("请先处理上面的审批，或点停止");
  await expect(composer).toBeVisible();
  await expect(composer).toBeFocused();
  await page.getByRole("button", { name: "同意", exact: true }).click();
  // 处理完以后卡片收起，决定并入工具行
  await expect(page.getByText("已同意")).toBeVisible();
  await expect(page.getByRole("group", { name: "等你确认" })).toHaveCount(0);
  await expect(page.getByText("记好了")).toBeVisible();
});

test("审批：修改后执行显示新参数", async ({ page }) => {
  await newThread(page);
  await send(page, "记笔记");
  await page.getByRole("button", { name: "修改后执行" }).click();
  await page.getByLabel("修改参数").fill('{"text": "买豆浆"}');
  await page.getByRole("button", { name: "确定，按新参数执行" }).click();
  await expect(page.getByText("修改后的参数（实际执行的）")).toBeVisible();
  await expect(page.getByText("记好了")).toBeVisible();
  // 折叠着的工具行里也有这段参数（看不见），只看显示出来的那处
  await expect(page.getByText('"text": "买豆浆"').filter({ visible: true }).first()).toBeVisible();
});

test("只问执行命令：外部工具不再弹审批", async ({ page }) => {
  await newThread(page);
  const chip = page.getByRole("button", { name: /每次先问/ });
  await chip.click();
  await expect(page.getByRole("menuitemradio")).toHaveCount(3);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toHaveCount(0);

  await chip.click();
  const saved = page.waitForResponse(
    (resp) => resp.request().method() === "PATCH" && resp.url().includes("/api/threads/"),
  );
  await page.getByRole("menuitemradio", { name: /只问执行命令/ }).click();
  expect((await saved).ok()).toBe(true);
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /只问执行命令/ })).toBeVisible();

  await send(page, "记笔记");
  await expect(page.getByText("记好了")).toBeVisible();
  await expect(page.getByText("要调用 demo · add_note 吗？")).toHaveCount(0);
});
