import { defineConfig } from "@playwright/test";

/**
 * 端到端测试（make e2e，设计文档 14 节）：驱动本机已装的 Chrome（不另下载浏览器），
 * 后端是 backend/tests/e2e_server.py（测试库 + 按剧本回复的假模型），共用一个后端，按顺序跑。
 */
export default defineConfig({
  testDir: "e2e",
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: { channel: "chrome", headless: true, baseURL: "http://127.0.0.1:8100" },
  webServer: {
    command: "uv run python -m backend.tests.e2e_server",
    cwd: "..",
    url: "http://127.0.0.1:8100/api/health",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
