import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { configDefaults } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  // e2e/ 是 Playwright 的浏览器测试（make e2e），不归单元测试
  test: { environment: "node", exclude: [...configDefaults.exclude, "e2e/**"] },
});
