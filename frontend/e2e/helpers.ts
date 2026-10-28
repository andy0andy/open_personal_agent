import { expect, type Page } from "@playwright/test";

/**
 * 绕过界面直接调接口时要带的请求头：本机令牌（D25，写操作只认请求头）。
 * 向后端取令牌（只校验 Host），与界面取的是同一个。
 */
export async function tokenHeaders(page: Page): Promise<Record<string, string>> {
  const resp = await page.request.get("/api/session");
  const { token } = (await resp.json()) as { token: string };
  return { "X-Session-Token": token };
}

/** 打开应用并新建一个会话（每个测试都从新会话开始）。 */
export async function newThread(page: Page): Promise<void> {
  await page.goto("/chat");
  await page.getByRole("button", { name: "新建会话" }).click();
  await expect(page.getByPlaceholder("给智能体发消息…")).toBeVisible();
}

/** 发一条消息（回车发送）。剧本按消息里的关键词选择，见 backend/tests/e2e_server.py。 */
export async function send(page: Page, text: string): Promise<void> {
  const box = page.getByPlaceholder("给智能体发消息…");
  await box.fill(text);
  await box.press("Enter");
}

/** 在对话页的会话栏里点开一个会话：标题就是首条消息（假模型不生成标题）。 */
export async function openThread(page: Page, title: string): Promise<void> {
  await page
    .getByRole("navigation", { name: "会话列表" })
    .getByText(title, { exact: true })
    .click();
}
