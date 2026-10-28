import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig(
  { ignores: ["dist", "src/api/generated", "test-results", "playwright-report"] },
  js.configs.recommended,
  tseslint.configs.strict,
  reactHooks.configs.flat.recommended,
  { languageOptions: { globals: globals.browser } },
  {
    // 复杂度与语句数的上限（设计 2026-10-23 7.4，同后端的 ruff C901、PLR0915）：超了就拆小
    rules: { complexity: ["error", 20], "max-statements": ["error", 50] },
  },
  {
    // assistant-ui 只能在对话组件层使用，其他代码通过 components/chat 的导出间接使用（设计文档 13.1）
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/components/chat/**"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@assistant-ui/*"],
              message: "assistant-ui 只能在 src/components/chat/ 中使用（设计文档 13.1）",
            },
          ],
        },
      ],
    },
  },
);
