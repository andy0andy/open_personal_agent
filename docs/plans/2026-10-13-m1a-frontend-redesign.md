# M1a 前端改版与一键启动 实施计划

> **给执行者：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐个任务执行本计划。步骤用复选框（`- [ ]`）跟踪。开始任何任务前先读 `.claude/skills/dev-standards/SKILL.md`。

**目标：** 前端换成"主题即数据"的设计系统（默认主题深浅两版，参考 Hermes Agent）与 assistant-ui 对话层、按新布局重做界面，并实现一键启动（`make up` 后打开 http://127.0.0.1:8000）。

**架构：** 主题文件（纯数据）→ 根节点 CSS 变量 → `color-mix` 派生色 → Tailwind 语义样式类；组件只用语义样式类。对话区用 assistant-ui 的基础组件，经"外部数据源"接法对接现有事件处理器，且只在 `frontend/src/components/chat/` 一层使用。backend 镜像改为多阶段构建，内含打包好的前端，由 FastAPI 在 `/` 提供、未知页面路径回退首页、`/api` 不受影响。

**技术栈：** 新增 `@assistant-ui/react` 0.15.28、`@assistant-ui/react-markdown` 0.14.21、`lucide-react` 1.55.0；移除 `react-markdown`；构建镜像 `mirror.gcr.io/library/node:24.21.0-trixie-slim`；其余同 M0。

**设计文档：** `docs/specs/2026-10-10-personal-agent-design.md`（第 5 版）第 13 节、D16、第 21 节 M1。本计划是 M1 拆分后的前半部分（M1a）；取消、思考过程、子智能体、用量、事件分批写库、安全防护、类型自动生成等在 M1b。

> 本计划的全部代码在写计划时已于临时目录实际运行验证：前端 7 个测试文件 21 个测试、Python 单元测试 25 个、`make check` 全部通过；浏览器中验证了深浅色切换、真实对话逐字输出、Markdown 表格、工具卡片；多阶段镜像构建成功，`make up` 后 `:8000` 提供新界面。

## 全局约束

- 直接依赖一律写精确版本（D12）；pnpm 11 会拒绝发布不足一天的版本——遇到时改选更早的稳定版本，**不要**接受它自动生成的 `pnpm-workspace.yaml` 豁免。
- 第三方服务一律由 `deploy/docker-compose.yml` 管理（D13）；镜像写死版本。
- 组件只用语义样式类（`bg-background`、`bg-card`、`bg-secondary`、`bg-muted`、`bg-accent`、`text-foreground`、`text-muted-foreground`、`border-border`、`bg-primary`、`text-primary-foreground`、`text-danger`、`text-success`、`text-warning`、`border-ring` 等），**不写具体颜色**；颜色、字体、圆角只在 `frontend/src/themes/` 与 `frontend/src/styles/` 中定义（设计文档 13.2）。
- assistant-ui 只能在 `frontend/src/components/chat/` 中使用（D16、设计文档 13.1）。
- 默认主题：深色背景 `#041c1c` / 主色 `#ffe6cb`；浅色背景 `#fbf7f0` / 主色 `#0b3b3a`；状态色 danger `#fb2c36`、success `#4ade80`、warning `#ffbd38`；系统字体、基准 15px、行高 1.55、圆角 0.5rem。
- 深浅色偏好存储键 `opa.color-mode`，取值 `system` / `dark` / `light`。
- 前端命令一律通过 `make` 执行，或先把 `~/.nvm/versions/node/v24.21.0/bin` 加到 `PATH` 前面。
- 注释与文档用中文，代码标识符用英文。
- **当前不是 git 仓库：不执行任何 git 命令**；每个任务以"检查点"结束。

## 重点关注

1. **刷新页面时深浅色闪一下** → 首屏就是正确颜色：`index.html` 内联脚本先设 `data-mode`，`tokens.css` 的默认值等于默认主题。测试：任务 1 `themes.test.ts`「tokens.css 的首屏默认值与默认主题一致」。
2. **浏览器禁用本地存储（隐私模式等）** → 外观设置照常可用（退回跟随系统、只在本次会话生效），不报错。测试：任务 1 `mode.test.ts`「读取保存过的选择；无效值、没有存储或存储报错时退回跟随系统」。
3. **发送失败**（后端停止、409 等）→ 显示错误、不留"幽灵消息"、输入框恢复原文。测试：任务 2 `adapter.test.ts`「发送失败时只有错误项」+ 任务 5 浏览器验证第 6 步。
4. **在浏览器里直接打开或刷新某个页面路径** → 返回前端首页；而写错的 `/api/...` 仍返回 JSON 404。测试：任务 4 `test_serves_built_frontend_with_spa_fallback`。
5. **后端重启期间模型列表加载失败** → 显示"正在重试"，恢复后自动出现列表，不需要刷新。测试：任务 3 `queries.test.ts`「加载失败时每 5 秒重试」+ 任务 5 浏览器验证第 7 步。

## 文件结构（本计划涉及）

```
frontend/
├── index.html                       # 改：首屏深浅色内联脚本
├── package.json / pnpm-lock.yaml    # 改：新增 assistant-ui、lucide-react，移除 react-markdown
├── tsconfig.json                    # 改：types 增加 node（测试读文件）
├── eslint.config.js                 # 改：限制 assistant-ui 的引用位置
└── src/
    ├── App.tsx                      # 改：ThemeProvider + AppShell
    ├── index.css                    # 改：引入令牌与排版样式
    ├── themes/                      # 新：types / default / registry / apply / mode / ThemeProvider + 测试
    ├── styles/                      # 新：tokens.css / markdown.css / no-raw-colors.test.ts
    ├── components/chat/             # 新：adapter / parts / ChatThread / index + 测试
    ├── layout/AppShell.tsx          # 新：整体布局
    ├── api/client.ts / queries.ts   # 改：可读错误信息、模型列表失败重试、会话列表查询
    └── features/
        ├── chat/ChatView.tsx        # 改：改用 ChatThread；删除 Composer、MessageList、keys
        ├── threads/ThreadList.tsx   # 改：新样式，按 id 选择
        ├── models/ModelSelect.tsx   # 改：新样式，失败自动重试
        └── settings/AppearanceToggle.tsx  # 新：跟随系统 / 深色 / 浅色
backend/frontend.py                  # 新：提供打包好的前端（未知页面路径回退首页）
backend/main.py                      # 改：create_app 增加 frontend_dist 参数并挂载前端
deploy/backend.Dockerfile            # 改：多阶段构建（先打包前端）
deploy/docker-compose.yml            # 改：backend 只接收需要的环境变量
.dockerignore / Makefile             # 改：带上前端源码；DC 增加 --env-file
docs/…、README.md、CLAUDE.md          # 改：规范、决策记录 D16、需求池、变更记录
```

---

### 任务 1：前端依赖与主题系统

**文件：**
- 修改：`frontend/package.json`、`frontend/pnpm-lock.yaml`（由 pnpm 命令生成）、`frontend/tsconfig.json`、`frontend/src/index.css`
- 新建：`frontend/src/themes/types.ts`、`default.ts`、`registry.ts`、`apply.ts`、`mode.ts`、`ThemeProvider.tsx`；`frontend/src/styles/tokens.css`、`markdown.css`
- 测试：`frontend/src/themes/themes.test.ts`、`frontend/src/themes/mode.test.ts`

**接口：**
- 产出：`ThemeDefinition`、`ColorMode`（`"dark" | "light"`）；`THEMES`、`DEFAULT_THEME`；`themeVariables(theme, mode): Record<string, string>`、`applyTheme(root, theme, mode)`；`ModePreference`（`"system" | ColorMode`）、`MODE_STORAGE_KEY = "opa.color-mode"`、`resolveMode(preference, prefersDark)`、`loadPreference(storage)`、`savePreference(storage, preference)`、`browserStorage()`；`ThemeProvider`、`useTheme(): { preference, mode, setPreference }`；CSS 语义色 `--color-background / foreground / card / secondary / muted / accent / border / ring / muted-foreground / primary / primary-foreground / danger / success / warning`。

- [ ] **步骤 1：新增依赖**（`react-markdown` 仍被旧组件使用，到任务 3 删除旧组件时再移除）

```bash
cd frontend
PATH=$HOME/.nvm/versions/node/v24.21.0/bin:$PATH pnpm add -E @assistant-ui/react@0.15.28 @assistant-ui/react-markdown@0.14.21 lucide-react@1.55.0
ls pnpm-workspace.yaml 2>/dev/null && echo "出现豁免文件，按全局约束处理" || echo ok
```
预期：安装成功，最后一行输出 `ok`。

- [ ] **步骤 2：`frontend/tsconfig.json` 的 `types` 增加 `node`**（测试需要读取文件）

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2023", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "noEmit": true,
    "types": ["vite/client", "node"]
  },
  "include": ["src", "vite.config.ts"]
}
```

- [ ] **步骤 3：写失败的测试**

`frontend/src/themes/themes.test.ts`：

```ts
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { themeVariables } from "./apply";
import { DEFAULT_THEME, THEMES } from "./registry";
import type { ColorMode } from "./types";

const HEX = /^#[0-9a-f]{6}$/i;
const MODES: ColorMode[] = ["dark", "light"];
const tokensCss = readFileSync(new URL("../styles/tokens.css", import.meta.url), "utf8");

function cssBlock(selector: string): string {
  const start = tokensCss.indexOf(`${selector} {`);
  return tokensCss.slice(start, tokensCss.indexOf("}", start));
}

function declared(block: string): Record<string, string> {
  return Object.fromEntries(
    [...block.matchAll(/(--theme-[a-z-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2]?.trim() ?? ""]),
  );
}

describe("主题契约", () => {
  it.each(THEMES.map((theme) => [theme.name, theme] as const))(
    "主题 %s 的深浅两版都提供合法的基础色",
    (_, theme) => {
      for (const mode of MODES) {
        expect(theme.modes[mode].background).toMatch(HEX);
        expect(theme.modes[mode].primary).toMatch(HEX);
      }
      for (const color of Object.values(theme.status)) expect(color).toMatch(HEX);
      expect(theme.typography.fontSans).not.toBe("");
      expect(theme.typography.fontMono).not.toBe("");
    },
  );

  it("主题变量与 tokens.css 中声明的变量一一对应", () => {
    const names = Object.keys(declared(cssBlock(":root"))).sort();
    for (const theme of THEMES) {
      expect(Object.keys(themeVariables(theme, "dark")).sort()).toEqual(names);
    }
  });

  it("tokens.css 的首屏默认值与默认主题一致（脚本运行前不闪烁）", () => {
    const dark = declared(cssBlock(":root"));
    const light = declared(cssBlock(':root[data-mode="light"]'));
    for (const [name, value] of Object.entries(themeVariables(DEFAULT_THEME, "dark"))) {
      expect(dark[name], name).toBe(value);
    }
    expect(light["--theme-background"]).toBe(DEFAULT_THEME.modes.light.background);
    expect(light["--theme-primary"]).toBe(DEFAULT_THEME.modes.light.primary);
  });
});
```

`frontend/src/themes/mode.test.ts`：

```ts
import { describe, expect, it } from "vitest";
import { loadPreference, MODE_STORAGE_KEY, resolveMode, savePreference } from "./mode";

describe("深浅色偏好", () => {
  it("跟随系统时按系统设置决定，固定时忽略系统设置", () => {
    expect(resolveMode("system", true)).toBe("dark");
    expect(resolveMode("system", false)).toBe("light");
    expect(resolveMode("light", true)).toBe("light");
  });

  it("读取保存过的选择；无效值、没有存储或存储报错时退回跟随系统", () => {
    const saved = new Map<string, string>();
    const storage = {
      getItem: (key: string) => saved.get(key) ?? null,
      setItem: (key: string, value: string) => void saved.set(key, value),
    };
    savePreference(storage, "light");
    expect(saved.get(MODE_STORAGE_KEY)).toBe("light");
    expect(loadPreference(storage)).toBe("light");

    saved.set(MODE_STORAGE_KEY, "purple");
    expect(loadPreference(storage)).toBe("system");
    expect(loadPreference(null)).toBe("system");
    expect(
      loadPreference({
        getItem: () => {
          throw new Error("SecurityError");
        },
      }),
    ).toBe("system");
  });
});
```

- [ ] **步骤 4：运行测试，确认失败**

运行：`cd frontend && PATH=$HOME/.nvm/versions/node/v24.21.0/bin:$PATH pnpm exec vitest run src/themes`
预期：FAIL，`Failed to resolve import "./apply"` / `"./mode"`。

- [ ] **步骤 5：写主题系统**

`frontend/src/themes/types.ts`：

```ts
/** 主题即数据：组件只用语义样式类，具体取值都来自这里（设计文档 13.2）。 */

export type ColorMode = "dark" | "light";

/** 一种深浅模式下的基础色。其余颜色由这两个基础色按比例混合派生（见 styles/tokens.css）。 */
export interface ModeColors {
  /** 背景色。 */
  background: string;
  /** 主色：正文文字、强调、用户消息气泡。 */
  primary: string;
}

export interface ThemeDefinition {
  name: string;
  label: string;
  modes: Record<ColorMode, ModeColors>;
  /** 状态色在深浅两种模式下保持不变。 */
  status: { danger: string; success: string; warning: string };
  typography: { fontSans: string; fontMono: string; baseSize: string; lineHeight: string };
  layout: { radius: string; density: "compact" | "comfortable" };
}
```

`frontend/src/themes/default.ts`：

```ts
import type { ThemeDefinition } from "./types";

/** 默认主题：深色科技感，参考 Hermes Agent 的 "Hermes Teal"。 */
export const defaultTheme: ThemeDefinition = {
  name: "default",
  label: "默认",
  modes: {
    dark: { background: "#041c1c", primary: "#ffe6cb" },
    light: { background: "#fbf7f0", primary: "#0b3b3a" },
  },
  status: { danger: "#fb2c36", success: "#4ade80", warning: "#ffbd38" },
  typography: {
    fontSans: 'system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    fontMono: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
    baseSize: "15px",
    lineHeight: "1.55",
  },
  layout: { radius: "0.5rem", density: "comfortable" },
};
```

`frontend/src/themes/registry.ts`：

```ts
import { defaultTheme } from "./default";
import type { ThemeDefinition } from "./types";

/** 主题登记表：新增主题 = 新增一个主题文件 + 在这里登记一行，组件不用改。 */
export const THEMES: readonly ThemeDefinition[] = [defaultTheme];

export const DEFAULT_THEME = defaultTheme;
```

`frontend/src/themes/apply.ts`：

```ts
import type { ColorMode, ThemeDefinition } from "./types";

/** 主题在某个模式下对应的 CSS 变量；名字必须与 styles/tokens.css 里 :root 声明的一致。 */
export function themeVariables(theme: ThemeDefinition, mode: ColorMode): Record<string, string> {
  const colors = theme.modes[mode];
  return {
    "--theme-background": colors.background,
    "--theme-primary": colors.primary,
    "--theme-danger": theme.status.danger,
    "--theme-success": theme.status.success,
    "--theme-warning": theme.status.warning,
    "--theme-font-sans": theme.typography.fontSans,
    "--theme-font-mono": theme.typography.fontMono,
    "--theme-base-size": theme.typography.baseSize,
    "--theme-line-height": theme.typography.lineHeight,
    "--theme-radius": theme.layout.radius,
    "--theme-spacing": theme.layout.density === "compact" ? "0.22rem" : "0.25rem",
  };
}

/** 把主题写到根节点上：data-theme / data-mode 属性 + CSS 变量。 */
export function applyTheme(root: HTMLElement, theme: ThemeDefinition, mode: ColorMode): void {
  root.dataset.theme = theme.name;
  root.dataset.mode = mode;
  root.style.colorScheme = mode;
  for (const [name, value] of Object.entries(themeVariables(theme, mode))) {
    root.style.setProperty(name, value);
  }
}
```

`frontend/src/themes/mode.ts`：

```ts
import type { ColorMode } from "./types";

export type ModePreference = "system" | ColorMode;

/** 与 index.html 中的内联脚本使用同一个键。 */
export const MODE_STORAGE_KEY = "opa.color-mode";

const PREFERENCES: readonly ModePreference[] = ["system", "dark", "light"];

export function resolveMode(preference: ModePreference, prefersDark: boolean): ColorMode {
  if (preference !== "system") return preference;
  return prefersDark ? "dark" : "light";
}

/** 读取用户选择；浏览器禁用本地存储或值无效时退回"跟随系统"。 */
export function loadPreference(storage: Pick<Storage, "getItem"> | null): ModePreference {
  try {
    const value = storage?.getItem(MODE_STORAGE_KEY);
    return PREFERENCES.find((preference) => preference === value) ?? "system";
  } catch {
    return "system";
  }
}

export function savePreference(
  storage: Pick<Storage, "setItem"> | null,
  preference: ModePreference,
): void {
  try {
    storage?.setItem(MODE_STORAGE_KEY, preference);
  } catch {
    // 本地存储不可用时只在本次会话生效
  }
}

export function browserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}
```

`frontend/src/themes/ThemeProvider.tsx`：

```tsx
import {
  createContext,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { applyTheme } from "./apply";
import {
  browserStorage,
  loadPreference,
  resolveMode,
  savePreference,
  type ModePreference,
} from "./mode";
import { DEFAULT_THEME } from "./registry";
import type { ColorMode } from "./types";

interface ThemeContextValue {
  preference: ModePreference;
  mode: ColorMode;
  setPreference: (preference: ModePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const DARK_QUERY = "(prefers-color-scheme: dark)";

function subscribeSystemMode(onChange: () => void): () => void {
  const media = window.matchMedia(DARK_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

const systemPrefersDark = () => window.matchMedia(DARK_QUERY).matches;

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ModePreference>(() =>
    loadPreference(browserStorage()),
  );
  const prefersDark = useSyncExternalStore(subscribeSystemMode, systemPrefersDark);
  const mode = resolveMode(preference, prefersDark);

  useEffect(() => {
    applyTheme(document.documentElement, DEFAULT_THEME, mode);
  }, [mode]);

  const setPreference = (next: ModePreference) => {
    setPreferenceState(next);
    savePreference(browserStorage(), next);
  };

  return <ThemeContext value={{ preference, mode, setPreference }}>{children}</ThemeContext>;
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme 必须在 ThemeProvider 内使用");
  return value;
}
```

- [ ] **步骤 6：写令牌与排版样式**

`frontend/src/styles/tokens.css`：

```css
/*
 * 主题令牌（设计文档 13.2）：组件只使用这里映射出的语义样式类，不写具体颜色。
 * :root 中的默认值等于默认主题（themes/default.ts），保证脚本运行前首屏颜色就正确；
 * 两处的一致性由 themes/themes.test.ts 检查。
 */
:root {
  --theme-background: #041c1c;
  --theme-primary: #ffe6cb;
  --theme-danger: #fb2c36;
  --theme-success: #4ade80;
  --theme-warning: #ffbd38;
  --theme-font-sans:
    system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  --theme-font-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  --theme-base-size: 15px;
  --theme-line-height: 1.55;
  --theme-radius: 0.5rem;
  --theme-spacing: 0.25rem;
  color-scheme: dark;
}

:root[data-mode="light"] {
  --theme-background: #fbf7f0;
  --theme-primary: #0b3b3a;
  color-scheme: light;
}

/* 由两个基础色派生其余颜色（比例参考 Hermes Agent） */
@theme inline {
  --color-background: var(--theme-background);
  --color-foreground: var(--theme-primary);
  --color-card: color-mix(in srgb, var(--theme-primary) 4%, var(--theme-background));
  --color-secondary: color-mix(in srgb, var(--theme-primary) 6%, var(--theme-background));
  --color-muted: color-mix(in srgb, var(--theme-primary) 8%, var(--theme-background));
  --color-accent: color-mix(in srgb, var(--theme-primary) 11%, var(--theme-background));
  --color-border: color-mix(in srgb, var(--theme-primary) 15%, var(--theme-background));
  --color-ring: color-mix(in srgb, var(--theme-primary) 45%, var(--theme-background));
  --color-muted-foreground: color-mix(in srgb, var(--theme-primary) 62%, var(--theme-background));
  --color-primary: var(--theme-primary);
  --color-primary-foreground: var(--theme-background);
  --color-danger: var(--theme-danger);
  --color-success: var(--theme-success);
  --color-warning: var(--theme-warning);
  --font-sans: var(--theme-font-sans);
  --font-mono: var(--theme-font-mono);
  --radius-sm: calc(var(--theme-radius) * 0.6);
  --radius-md: calc(var(--theme-radius) * 0.8);
  --radius-lg: var(--theme-radius);
  --radius-xl: calc(var(--theme-radius) * 1.5);
  --spacing: var(--theme-spacing);
}

html {
  font-size: var(--theme-base-size);
}

body {
  margin: 0;
  background: var(--color-background);
  color: var(--color-foreground);
  font-family: var(--font-sans);
  line-height: var(--theme-line-height);
  -webkit-font-smoothing: antialiased;
}

/* 顶部一层很淡的暖光，营造 Hermes 风格的层次感 */
.app-glow {
  background-image: radial-gradient(
    60rem 28rem at 15% -10%,
    color-mix(in srgb, var(--theme-warning) 10%, transparent),
    transparent 70%
  );
}

::selection {
  background: color-mix(in srgb, var(--theme-primary) 25%, transparent);
}
```

`frontend/src/styles/markdown.css`：

```css
/* Markdown 回答的排版：全部读主题令牌 */
.markdown {
  overflow-wrap: anywhere;
}
.markdown > :first-child {
  margin-top: 0;
}
.markdown > :last-child {
  margin-bottom: 0;
}
.markdown p,
.markdown ul,
.markdown ol,
.markdown pre,
.markdown table,
.markdown blockquote {
  margin: 0.6rem 0;
}
.markdown h1,
.markdown h2,
.markdown h3 {
  margin: 1rem 0 0.5rem;
  font-weight: 600;
  line-height: 1.3;
}
.markdown h1 {
  font-size: 1.35rem;
}
.markdown h2 {
  font-size: 1.2rem;
}
.markdown h3 {
  font-size: 1.05rem;
}
.markdown ul {
  list-style: disc;
  padding-left: 1.4rem;
}
.markdown ol {
  list-style: decimal;
  padding-left: 1.4rem;
}
.markdown a {
  color: var(--color-warning);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.markdown code {
  font-family: var(--font-mono);
  font-size: 0.88em;
  border-radius: var(--radius-sm);
  background: var(--color-muted);
  padding: 0.1rem 0.3rem;
}
.markdown pre {
  overflow-x: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-card);
  padding: 0.75rem 0.9rem;
}
.markdown pre code {
  background: transparent;
  padding: 0;
}
.markdown blockquote {
  border-left: 3px solid var(--color-border);
  padding-left: 0.8rem;
  color: var(--color-muted-foreground);
}
.markdown table {
  border-collapse: collapse;
  font-size: 0.92em;
}
.markdown th,
.markdown td {
  border: 1px solid var(--color-border);
  padding: 0.35rem 0.6rem;
  text-align: left;
}
.markdown th {
  background: var(--color-secondary);
  font-weight: 600;
}
```

`frontend/src/index.css`（整个替换）：

```css
@import "tailwindcss";
@import "./styles/tokens.css";
@import "./styles/markdown.css";
```

- [ ] **步骤 7：运行测试，确认通过**

运行：`cd frontend && PATH=$HOME/.nvm/versions/node/v24.21.0/bin:$PATH pnpm exec vitest run src/themes`
预期：2 个测试文件、5 个测试通过。

- [ ] **步骤 8：检查点**

运行：`make check`
预期：全部通过（此时旧组件仍在使用写死的颜色，写死颜色检查在任务 3 才加入）。

---

### 任务 2：assistant-ui 对话组件层

**文件：**
- 新建：`frontend/src/components/chat/adapter.ts`、`parts.tsx`、`ChatThread.tsx`、`index.ts`
- 修改：`frontend/eslint.config.js`
- 测试：`frontend/src/components/chat/adapter.test.ts`

**接口：**
- 消费：`features/chat/reducer.ts` 的 `ChatState` / `ChatItem`（M0，不变）。
- 产出：`toThreadMessages(state: ChatState): ThreadMessageLike[]`；`ChatThread({ state, onSend }: { state: ChatState; onSend: (text: string) => Promise<boolean> })`——`onSend` 返回 `false` 时输入框恢复原文；`components/chat/index.ts` 只导出 `ChatThread`。

- [ ] **步骤 1：写失败的测试** `frontend/src/components/chat/adapter.test.ts`

```ts
import { describe, expect, it } from "vitest";
import type { ChatState } from "../../features/chat/reducer";
import { toThreadMessages } from "./adapter";

const finished: ChatState = {
  running: false,
  items: [
    { kind: "user", id: "u1", text: "hi" },
    {
      kind: "tool",
      id: "tool-c1",
      name: "ls",
      args: { path: "/" },
      status: "success",
      output: "无文件",
    },
    { kind: "assistant", id: "msg-m1", text: "你好" },
    { kind: "user", id: "u2", text: "再来" },
    { kind: "error", id: "err-r2", text: "模型网关不可用" },
  ],
};

describe("toThreadMessages", () => {
  it("用户消息之间的工具调用与回答合并为一条助手消息，顺序不变", () => {
    const messages = toThreadMessages(finished);
    expect(messages.map((message) => message.role)).toEqual([
      "user",
      "assistant",
      "user",
      "assistant",
    ]);
    expect(messages[1]?.content).toEqual([
      {
        type: "tool-call",
        toolCallId: "tool-c1",
        toolName: "ls",
        argsText: '{\n  "path": "/"\n}',
        result: "无文件",
        isError: false,
      },
      { type: "text", text: "你好" },
    ]);
  });

  it("失败的运行映射为带错误原因的未完成消息", () => {
    expect(toThreadMessages(finished)[3]?.status).toEqual({
      type: "incomplete",
      reason: "error",
      error: "模型网关不可用",
    });
  });

  it("发送失败时只有错误项，也能单独成为一条助手消息", () => {
    const state: ChatState = {
      running: false,
      items: [{ kind: "error", id: "err-1", text: "请求失败：502" }],
    };
    expect(toThreadMessages(state)).toEqual([
      {
        id: "a-err-1",
        role: "assistant",
        content: [],
        status: { type: "incomplete", reason: "error", error: "请求失败：502" },
      },
    ]);
  });

  it("进行中的最后一条助手消息标记为 running；工具未结束时没有结果", () => {
    const running: ChatState = {
      running: true,
      items: [
        { kind: "user", id: "u1", text: "hi" },
        { kind: "tool", id: "tool-c1", name: "ls", args: {}, status: "running", output: "" },
      ],
    };
    const [, assistant] = toThreadMessages(running);
    expect(assistant?.status).toEqual({ type: "running" });
    expect(assistant?.content).toEqual([
      { type: "tool-call", toolCallId: "tool-c1", toolName: "ls", argsText: "{}" },
    ]);
  });
});
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`cd frontend && PATH=$HOME/.nvm/versions/node/v24.21.0/bin:$PATH pnpm exec vitest run src/components`
预期：FAIL，`Failed to resolve import "./adapter"`。

- [ ] **步骤 3：写转换函数** `frontend/src/components/chat/adapter.ts`

```ts
import type { ThreadMessageLike } from "@assistant-ui/react";
import type { ChatItem, ChatState } from "../../features/chat/reducer";

type AssistantPart = Exclude<ThreadMessageLike["content"], string>[number];

/**
 * 把事件处理器的状态转换成 assistant-ui 的消息（设计文档 13.1 映射表）：
 * 两条用户消息之间的回答与工具调用合并为一条助手消息；运行失败映射为"未完成"并带错误原因。
 */
export function toThreadMessages(state: ChatState): ThreadMessageLike[] {
  const groups: ChatItem[][] = [];
  for (const item of state.items) {
    const last = groups.at(-1);
    if (item.kind !== "user" && last && last[0]?.kind !== "user") last.push(item);
    else groups.push([item]);
  }
  return groups.map((group, index) => {
    const first = group[0];
    if (first?.kind === "user") {
      return { id: first.id, role: "user", content: [{ type: "text", text: first.text }] };
    }
    const parts: AssistantPart[] = [];
    let error: string | null = null;
    for (const item of group) {
      if (item.kind === "assistant") parts.push({ type: "text", text: item.text });
      else if (item.kind === "tool")
        parts.push({
          type: "tool-call",
          toolCallId: item.id,
          toolName: item.name,
          argsText: JSON.stringify(item.args, null, 2),
          ...(item.status === "running"
            ? {}
            : { result: item.output, isError: item.status === "error" }),
        });
      else if (item.kind === "error") error = item.text;
    }
    const running = index === groups.length - 1 && state.running;
    return {
      id: `a-${first?.id ?? index}`,
      role: "assistant",
      content: parts,
      status: error
        ? { type: "incomplete", reason: "error", error }
        : running
          ? { type: "running" }
          : { type: "complete", reason: "stop" },
    };
  });
}
```

- [ ] **步骤 4：运行测试，确认通过**

运行同步骤 2。预期：4 passed。

- [ ] **步骤 5：写对话组件**

`frontend/src/components/chat/parts.tsx`（Markdown 回答、工具卡片、用户 / 助手消息、错误提示、复制按钮）：

```tsx
import {
  ActionBarPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  type ToolCallMessagePartComponent,
} from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import { Check, ChevronRight, Copy, LoaderCircle, TriangleAlert, Wrench } from "lucide-react";
import remarkGfm from "remark-gfm";

const MarkdownText = () => (
  <MarkdownTextPrimitive remarkPlugins={[remarkGfm]} className="markdown" />
);

/** 工具调用卡片：默认折叠，展开后显示参数与结果。 */
export const ToolCard: ToolCallMessagePartComponent = ({ toolName, argsText, result, isError }) => {
  const done = result !== undefined;
  return (
    <details className="group my-2 rounded-lg border border-border bg-card text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-muted-foreground">
        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" />
        <Wrench className="size-3.5" />
        <span className="font-mono text-foreground">{toolName}</span>
        <span className="ml-auto flex items-center gap-1 text-xs">
          {!done && <LoaderCircle className="size-3.5 animate-spin" />}
          {done && isError && <TriangleAlert className="size-3.5 text-danger" />}
          {done && !isError && <Check className="size-3.5 text-success" />}
          {!done ? "运行中" : isError ? "出错" : "完成"}
        </span>
      </summary>
      <div className="space-y-2 border-t border-border px-3 py-2">
        <pre className="overflow-x-auto font-mono text-xs text-muted-foreground">{argsText}</pre>
        {done && (
          <pre className="overflow-x-auto font-mono text-xs whitespace-pre-wrap">
            {String(result)}
          </pre>
        )}
      </div>
    </details>
  );
};

export const UserMessage = () => (
  <MessagePrimitive.Root className="flex justify-end">
    <div className="max-w-[80%] rounded-xl rounded-br-sm bg-primary px-4 py-2.5 whitespace-pre-wrap text-primary-foreground">
      <MessagePrimitive.Parts />
    </div>
  </MessagePrimitive.Root>
);

export const AssistantMessage = () => (
  <MessagePrimitive.Root className="group relative">
    <MessagePrimitive.Parts components={{ Text: MarkdownText, tools: { Fallback: ToolCard } }} />
    <MessagePrimitive.Error>
      <ErrorPrimitive.Root className="mt-2 flex items-start gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
        <TriangleAlert className="mt-0.5 size-4 shrink-0" />
        <ErrorPrimitive.Message />
      </ErrorPrimitive.Root>
    </MessagePrimitive.Error>
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="mt-1 flex gap-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
    >
      <ActionBarPrimitive.Copy
        className="rounded-md p-1 hover:bg-muted hover:text-foreground"
        aria-label="复制"
      >
        <Copy className="size-3.5" />
      </ActionBarPrimitive.Copy>
    </ActionBarPrimitive.Root>
  </MessagePrimitive.Root>
);
```

`frontend/src/components/chat/ChatThread.tsx`：

```tsx
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  ThreadPrimitive,
  useExternalStoreRuntime,
  type AppendMessage,
} from "@assistant-ui/react";
import { ArrowUp, Sparkles } from "lucide-react";
import type { ChatState } from "../../features/chat/reducer";
import { toThreadMessages } from "./adapter";
import { AssistantMessage, UserMessage } from "./parts";

interface ChatThreadProps {
  state: ChatState;
  /** 发送成功返回 true；失败返回 false 时输入框恢复原文，方便直接重试。 */
  onSend: (text: string) => Promise<boolean>;
}

/** 对话区：消息列表 + 输入框。assistant-ui 只在 components/chat/ 这一层使用（设计文档 13.1）。 */
export function ChatThread({ state, onSend }: ChatThreadProps) {
  const runtime = useExternalStoreRuntime({
    messages: toThreadMessages(state),
    isRunning: state.running,
    convertMessage: (message) => message,
    onNew: async (message: AppendMessage) => {
      const text = message.content.map((part) => (part.type === "text" ? part.text : "")).join("");
      if (!(await onSend(text))) runtime.thread.composer.setText(text);
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col">
        <ThreadPrimitive.Viewport className="flex flex-1 flex-col overflow-y-auto">
          <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-8">
            <ThreadPrimitive.Empty>
              <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center text-muted-foreground">
                <Sparkles className="size-8 text-warning" />
                <p className="text-lg text-foreground">今天想做点什么？</p>
                <p className="text-sm">输入问题开始对话，Enter 发送，Shift+Enter 换行</p>
              </div>
            </ThreadPrimitive.Empty>
            <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
          </div>
        </ThreadPrimitive.Viewport>
        <div className="mx-auto w-full max-w-3xl px-6 pb-6">
          <ComposerPrimitive.Root className="flex items-end gap-2 rounded-xl border border-border bg-card p-2 shadow-lg focus-within:border-ring">
            <ComposerPrimitive.Input
              autoFocus
              rows={1}
              placeholder="给智能体发消息…"
              className="max-h-48 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 outline-none placeholder:text-muted-foreground"
            />
            <ComposerPrimitive.Send
              aria-label="发送"
              className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity disabled:opacity-30"
            >
              <ArrowUp className="size-4" />
            </ComposerPrimitive.Send>
          </ComposerPrimitive.Root>
        </div>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
```

`frontend/src/components/chat/index.ts`：

```ts
/** 对话组件层的唯一出口：其他代码只用这里导出的组件，不直接依赖 assistant-ui。 */
export { ChatThread } from "./ChatThread";
```

- [ ] **步骤 6：限制 assistant-ui 的引用位置** `frontend/eslint.config.js`（整个替换）

```js
import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig(
  { ignores: ["dist"] },
  js.configs.recommended,
  tseslint.configs.strict,
  reactHooks.configs.flat.recommended,
  { languageOptions: { globals: globals.browser } },
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
```

- [ ] **步骤 7：检查点**

运行：`make check`
预期：全部通过（`ChatThread` 尚未被页面使用，任务 3 接入）。

---

### 任务 3：新布局与界面改版

**文件：**
- 新建：`frontend/src/styles/no-raw-colors.test.ts`、`frontend/src/api/client.test.ts`、`frontend/src/features/settings/AppearanceToggle.tsx`、`frontend/src/layout/AppShell.tsx`
- 修改：`frontend/src/api/client.ts`、`frontend/src/api/queries.ts`、`frontend/src/api/queries.test.ts`、`frontend/src/features/models/ModelSelect.tsx`、`frontend/src/features/threads/ThreadList.tsx`、`frontend/src/features/chat/ChatView.tsx`、`frontend/src/App.tsx`、`frontend/index.html`
- 删除：`frontend/src/features/chat/Composer.tsx`、`MessageList.tsx`、`keys.ts`、`keys.test.ts`（输入框改用 assistant-ui，它已处理中文输入法回车，包括旧版 Safari 的 `keyCode 229`）

**接口：**
- 消费：任务 1 的 `ThemeProvider`、`useTheme`、`ModePreference`；任务 2 的 `ChatThread`。
- 产出：`errorMessage(status, body): string`；`threadsQuery`、`modelsQuery`、`retryWhileFailing(query): number | false`；`ThreadList({ selectedId, onSelect: (threadId: string) => void })`；`AppShell`。

- [ ] **步骤 1：写失败的测试**

写死颜色检查 `frontend/src/styles/no-raw-colors.test.ts`：

```ts
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/** 写死颜色检查（设计文档 13.2）：组件只能用语义样式类，具体颜色只能出现在主题与令牌文件中。 */
const SRC = fileURLToPath(new URL("..", import.meta.url));
const ALLOWED_DIRS = ["themes", "styles"];
const PALETTE =
  /\b(?:bg|text|border|ring|outline|fill|stroke|from|via|to|divide|placeholder|shadow|decoration|caret)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|black|white)(?:-\d{2,3})?\b/;
const LITERAL = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

describe("写死颜色检查", () => {
  it("组件代码中没有具体颜色", () => {
    const offenders = sourceFiles(SRC)
      .filter((path) => !ALLOWED_DIRS.includes(relative(SRC, path).split(sep)[0] ?? ""))
      .flatMap((path) =>
        readFileSync(path, "utf8")
          .split("\n")
          .map((line, index) => ({ line, at: `${relative(SRC, path)}:${index + 1}` }))
          .filter(({ line }) => PALETTE.test(line) || LITERAL.test(line))
          .map(({ at, line }) => `${at}  ${line.trim()}`),
      );
    expect(offenders).toEqual([]);
  });
});
```

`frontend/src/api/client.test.ts`（M4：422 错误可读）：

```ts
import { describe, expect, it } from "vitest";
import { errorMessage } from "./client";

describe("errorMessage", () => {
  it("detail 是字符串时直接使用", () => {
    expect(errorMessage(409, { detail: "该会话已有进行中的运行" })).toBe("该会话已有进行中的运行");
  });

  it("422 校验错误的 detail 是数组时，拼接其中的原因", () => {
    const body = {
      detail: [{ loc: ["body", "message"], msg: "String should have at least 1 character" }],
    };
    expect(errorMessage(422, body)).toBe("请求参数有误：String should have at least 1 character");
  });

  it("没有可读信息时给出状态码", () => {
    expect(errorMessage(502, null)).toBe("请求失败：502");
    expect(errorMessage(500, { detail: [{}] })).toBe("请求失败：500");
  });
});
```

`frontend/src/api/queries.test.ts`（整个替换，新增模型列表失败重试的测试）：

```ts
import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { historyQuery, retryWhileFailing } from "./queries";

describe("historyQuery", () => {
  it("离开会话后丢弃缓存的历史，再次进入会重新拉取", async () => {
    const client = new QueryClient();
    const queryFn = vi.fn(async () => []);
    const observer = new QueryObserver(client, { ...historyQuery("t1"), queryFn });
    const unsubscribe = observer.subscribe(() => undefined);
    await vi.waitFor(() => expect(queryFn).toHaveBeenCalledTimes(1));

    unsubscribe();
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(client.getQueryData(["history", "t1"])).toBeUndefined();
  });
});

describe("retryWhileFailing", () => {
  it("加载失败时每 5 秒重试，成功后停止", () => {
    expect(retryWhileFailing({ state: { status: "error" } } as never)).toBe(5000);
    expect(retryWhileFailing({ state: { status: "success" } } as never)).toBe(false);
  });
});
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`cd frontend && PATH=$HOME/.nvm/versions/node/v24.21.0/bin:$PATH pnpm test`
预期：写死颜色检查 FAIL，列出约 19 处（`App.tsx`、`ChatView.tsx`、`Composer.tsx`、`MessageList.tsx`、`ModelSelect.tsx`、`ThreadList.tsx` 中的 `bg-blue-600`、`text-gray-900` 等）；`client.test.ts`、`queries.test.ts` FAIL（`errorMessage` / `retryWhileFailing` 不存在）。

- [ ] **步骤 3：接口层**

`frontend/src/api/client.ts`（整个替换）：

```ts
import type { ModelInfo, RunHistory, RunRecord, Thread } from "./types";

/** 把后端的错误响应转成看得懂的一句话：FastAPI 的 422 校验错误的 detail 是数组。 */
export function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const reasons = detail
      .map((item) => (item as { msg?: unknown }).msg)
      .filter((msg): msg is string => typeof msg === "string");
    if (reasons.length > 0) return `请求参数有误：${reasons.join("；")}`;
  }
  return `请求失败：${status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!resp.ok) {
    throw new Error(errorMessage(resp.status, await resp.json().catch(() => null)));
  }
  return (await resp.json()) as T;
}

export const api = {
  listThreads: () => request<Thread[]>("/threads"),
  createThread: () => request<Thread>("/threads", { method: "POST", body: "{}" }),
  history: (threadId: string) => request<RunHistory[]>(`/threads/${threadId}/history`),
  listModels: () => request<ModelInfo[]>("/models"),
  startRun: (threadId: string, message: string, model: string) =>
    request<RunRecord>(`/threads/${threadId}/runs`, {
      method: "POST",
      body: JSON.stringify({ message, model }),
    }),
};
```

`frontend/src/api/queries.ts`（整个替换）：

```ts
import type { Query } from "@tanstack/react-query";
import { api } from "./client";

/**
 * 会话的界面历史查询。
 * 离开会话（组件卸载）后立即丢弃缓存：会话进行中界面状态是实时更新的、不回写缓存，
 * 若保留旧缓存，切回来时会用切走之前的历史重建界面，刚才的对话就"消失"了。
 */
export function historyQuery(threadId: string) {
  return {
    queryKey: ["history", threadId],
    queryFn: () => api.history(threadId),
    staleTime: Infinity,
    gcTime: 0,
  };
}

export const threadsQuery = { queryKey: ["threads"], queryFn: api.listThreads };

/** 失败后每 5 秒重试一次，直到成功（例如后端重启期间模型列表加载失败）。 */
export function retryWhileFailing(query: Pick<Query, "state">): number | false {
  return query.state.status === "error" ? 5000 : false;
}

export const modelsQuery = {
  queryKey: ["models"],
  queryFn: api.listModels,
  refetchInterval: retryWhileFailing,
};
```

- [ ] **步骤 4：功能组件**

`frontend/src/features/models/ModelSelect.tsx`（整个替换）：

```tsx
import { useQuery } from "@tanstack/react-query";
import { Cpu, TriangleAlert } from "lucide-react";
import { modelsQuery } from "../../api/queries";

export function ModelSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (model: string) => void;
}) {
  const models = useQuery(modelsQuery);
  const chatModels = (models.data ?? []).filter((model) => model.mode === "chat");

  if (models.isError && !models.data) {
    return (
      <span className="flex items-center gap-1.5 text-xs text-danger" title={String(models.error)}>
        <TriangleAlert className="size-3.5" />
        模型列表加载失败，正在重试…
      </span>
    );
  }

  return (
    <label className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-2 py-1 text-sm text-muted-foreground focus-within:border-ring">
      <Cpu className="size-3.5" />
      <select
        className="bg-transparent font-mono text-xs text-foreground outline-none"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {!chatModels.some((model) => model.name === value) && (
          <option value={value}>{value}</option>
        )}
        {chatModels.map((model) => (
          <option key={model.name} value={model.name}>
            {model.name}
          </option>
        ))}
      </select>
    </label>
  );
}
```

`frontend/src/features/settings/AppearanceToggle.tsx`：

```tsx
import { Monitor, Moon, Sun } from "lucide-react";
import type { ModePreference } from "../../themes/mode";
import { useTheme } from "../../themes/ThemeProvider";

const OPTIONS: { value: ModePreference; label: string; Icon: typeof Sun }[] = [
  { value: "system", label: "跟随系统", Icon: Monitor },
  { value: "dark", label: "深色", Icon: Moon },
  { value: "light", label: "浅色", Icon: Sun },
];

/** 外观切换：跟随系统 / 深色 / 浅色。 */
export function AppearanceToggle() {
  const { preference, setPreference } = useTheme();
  return (
    <div
      role="radiogroup"
      aria-label="外观"
      className="flex rounded-lg border border-border bg-card p-0.5"
    >
      {OPTIONS.map(({ value, label, Icon }) => (
        <button
          key={value}
          role="radio"
          aria-checked={preference === value}
          title={label}
          onClick={() => setPreference(value)}
          className={`flex flex-1 items-center justify-center rounded-md py-1 transition-colors ${
            preference === value
              ? "bg-accent text-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <Icon className="size-3.5" />
        </button>
      ))}
    </div>
  );
}
```

`frontend/src/features/threads/ThreadList.tsx`（整个替换）：

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquare, Plus } from "lucide-react";
import { api } from "../../api/client";
import { threadsQuery } from "../../api/queries";
import type { Thread } from "../../api/types";

export function ThreadList({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (threadId: string) => void;
}) {
  const queryClient = useQueryClient();
  const threads = useQuery(threadsQuery);
  const create = useMutation({
    mutationFn: api.createThread,
    onSuccess: (thread) => {
      queryClient.setQueryData<Thread[]>(threadsQuery.queryKey, (old) => [thread, ...(old ?? [])]);
      onSelect(thread.id);
    },
  });

  return (
    <nav className="flex min-h-0 flex-1 flex-col gap-3">
      <button
        className="flex items-center justify-center gap-2 rounded-lg border border-border bg-secondary px-3 py-2 text-sm transition-colors hover:bg-accent disabled:opacity-50"
        disabled={create.isPending}
        onClick={() => create.mutate()}
      >
        <Plus className="size-4" />
        新会话
      </button>
      {threads.isError && <p className="px-2 text-xs text-danger">会话列表加载失败</p>}
      <p className="px-2 font-mono text-[0.7rem] tracking-widest text-muted-foreground uppercase">
        会话
      </p>
      <ul className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
        {(threads.data ?? []).map((thread) => (
          <li key={thread.id}>
            <button
              className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors ${
                thread.id === selectedId
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
              onClick={() => onSelect(thread.id)}
            >
              <MessageSquare className="size-3.5 shrink-0" />
              <span className="truncate">{thread.title || "新会话"}</span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
```

`frontend/src/features/chat/ChatView.tsx`（整个替换）：

```tsx
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { subscribeRun } from "../../api/events";
import { historyQuery } from "../../api/queries";
import type { RunHistory, Thread } from "../../api/types";
import { ChatThread } from "../../components/chat";
import { ModelSelect } from "../models/ModelSelect";
import {
  addError,
  addUserMessage,
  applyEvent,
  chatFromHistory,
  removeItem,
  type ChatState,
} from "./reducer";

const ACTIVE = new Set(["queued", "running"]);

function ChatSession({ thread, history }: { thread: Thread; history: RunHistory[] }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<ChatState>(() => chatFromHistory(history));
  const [model, setModel] = useState(thread.model);
  const [activeRunId, setActiveRunId] = useState<string | null>(
    () => history.find((run) => ACTIVE.has(run.status))?.id ?? null,
  );

  useEffect(() => {
    if (!activeRunId) return;
    return subscribeRun(activeRunId, (event) => {
      setState((current) => applyEvent(current, event));
      if (event.type === "run.finished") setActiveRunId(null);
    });
  }, [activeRunId]);

  /** 发送成功返回 true；失败时撤回乐观显示的消息并显示错误，返回 false 让输入框恢复原文。 */
  const send = async (text: string): Promise<boolean> => {
    const userId = `user-${Date.now()}`;
    setState((current) => ({ ...addUserMessage(current, userId, text), running: true }));
    try {
      const run = await api.startRun(thread.id, text, model);
      setActiveRunId(run.id);
      void queryClient.invalidateQueries({ queryKey: ["threads"] });
      return true;
    } catch (error) {
      setState((current) =>
        addError(removeItem(current, userId), `err-${Date.now()}`, String(error)),
      );
      return false;
    }
  };

  return (
    <>
      <header className="flex items-center justify-between gap-4 border-b border-border px-6 py-3">
        <h1 className="truncate font-medium">{thread.title || "新会话"}</h1>
        <ModelSelect value={model} onChange={setModel} />
      </header>
      <ChatThread state={state} onSend={send} />
    </>
  );
}

export function ChatView({ thread }: { thread: Thread }) {
  const history = useQuery(historyQuery(thread.id));
  if (history.isError) {
    return <p className="p-6 text-sm text-danger">历史加载失败：{String(history.error)}</p>;
  }
  if (!history.data) {
    return (
      <p className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
        <LoaderCircle className="size-4 animate-spin" />
        加载中…
      </p>
    );
  }
  return <ChatSession key={thread.id} thread={thread} history={history.data} />;
}
```

删除旧组件，并移除不再使用的 `react-markdown`：

```bash
rm frontend/src/features/chat/Composer.tsx frontend/src/features/chat/MessageList.tsx frontend/src/features/chat/keys.ts frontend/src/features/chat/keys.test.ts
cd frontend && PATH=$HOME/.nvm/versions/node/v24.21.0/bin:$PATH pnpm remove react-markdown
```

此时 `frontend/package.json` 应为：

```json
{
  "name": "open-personal-agent-frontend",
  "private": true,
  "type": "module",
  "packageManager": "pnpm@11.17.0",
  "engines": {
    "node": ">=24.15.0 <25"
  },
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run",
    "lint": "eslint .",
    "format": "prettier --check ."
  },
  "dependencies": {
    "@assistant-ui/react": "0.15.28",
    "@assistant-ui/react-markdown": "0.14.21",
    "@tanstack/react-query": "5.104.1",
    "lucide-react": "1.55.0",
    "react": "19.3.0",
    "react-dom": "19.3.0",
    "remark-gfm": "4.0.1"
  },
  "devDependencies": {
    "@eslint/js": "10.0.1",
    "@tailwindcss/vite": "4.3.3",
    "@types/node": "24.19.2",
    "@types/react": "19.3.0",
    "@types/react-dom": "19.3.0",
    "@vitejs/plugin-react": "6.1.2",
    "eslint": "10.12.0",
    "eslint-plugin-react-hooks": "7.1.1",
    "globals": "17.13.0",
    "prettier": "3.9.10",
    "tailwindcss": "4.3.3",
    "typescript": "6.0.3",
    "typescript-eslint": "8.71.1",
    "vite": "8.3.4",
    "vitest": "5.0.3"
  }
}
```

- [ ] **步骤 5：布局与入口**

`frontend/src/layout/AppShell.tsx`（顶栏标题从会话列表实时读取——修复 M5）：

```tsx
import { useQuery } from "@tanstack/react-query";
import { Bot } from "lucide-react";
import { useState } from "react";
import { threadsQuery } from "../api/queries";
import { ChatView } from "../features/chat/ChatView";
import { AppearanceToggle } from "../features/settings/AppearanceToggle";
import { ThreadList } from "../features/threads/ThreadList";

/** 整体布局（参考 Hermes 的聊天页）：左侧会话栏 + 右侧对话区。 */
export function AppShell() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const threads = useQuery(threadsQuery);
  // 每次都从会话列表里取最新的会话对象，标题等信息随列表刷新而更新
  const thread = threads.data?.find((item) => item.id === selectedId) ?? null;

  return (
    <div className="app-glow flex h-screen bg-background text-foreground">
      <aside className="flex w-64 shrink-0 flex-col gap-4 border-r border-border bg-card/60 p-3">
        <div className="flex items-center gap-2 px-2 pt-1">
          <Bot className="size-5 text-warning" />
          <span className="font-mono text-sm tracking-widest uppercase">Personal Agent</span>
        </div>
        <ThreadList selectedId={selectedId} onSelect={setSelectedId} />
        <AppearanceToggle />
      </aside>
      <main className="flex min-w-0 flex-1 flex-col">
        {thread ? (
          <ChatView thread={thread} />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
            <Bot className="size-10 text-warning" />
            <p className="text-foreground">个人智能体</p>
            <p className="text-sm">从左侧选择会话，或新建一个会话开始对话</p>
          </div>
        )}
      </main>
    </div>
  );
}
```

`frontend/src/App.tsx`（整个替换）：

```tsx
import { AppShell } from "./layout/AppShell";
import { ThemeProvider } from "./themes/ThemeProvider";

export function App() {
  return (
    <ThemeProvider>
      <AppShell />
    </ThemeProvider>
  );
}
```

`frontend/index.html`（整个替换，首屏深浅色内联脚本）：

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>个人智能体</title>
    <script>
      // 在样式与脚本加载前先确定深浅色，避免刷新时闪一下（存储键与 src/themes/mode.ts 一致）
      (function () {
        var mode = "dark";
        try {
          var saved = localStorage.getItem("opa.color-mode");
          var prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
          mode = saved === "light" || saved === "dark" ? saved : prefersDark ? "dark" : "light";
        } catch (e) {}
        document.documentElement.dataset.mode = mode;
      })();
    </script>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **步骤 6：运行测试，确认通过**

运行同步骤 2。预期：7 个测试文件、21 个测试全部通过（写死颜色检查不再报任何位置）。

- [ ] **步骤 7：检查点**

运行：`make check`
预期：全部通过；`cd frontend && PATH=$HOME/.nvm/versions/node/v24.21.0/bin:$PATH pnpm build` 输出 `built in …`（脚本约 790KB，压缩后约 240KB）。

---

### 任务 4：一键启动

**文件：**
- 新建：`backend/frontend.py`、`backend/tests/test_frontend.py`
- 修改：`backend/main.py`、`deploy/backend.Dockerfile`、`.dockerignore`、`deploy/docker-compose.yml`、`Makefile`

**接口：**
- 产出：`FRONTEND_DIST`（项目根目录 `frontend/dist`）；`mount_frontend(app, dist) -> bool`；`create_app(lifespan_handler=lifespan, frontend_dist=FRONTEND_DIST)`。

- [ ] **步骤 1：写失败的测试** `backend/tests/test_frontend.py`

```python
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import create_app


def _dist(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<html>首页</html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return tmp_path


def test_serves_built_frontend_with_spa_fallback(tmp_path: Path) -> None:
    app = create_app(lifespan_handler=None, frontend_dist=_dist(tmp_path))
    with TestClient(app) as client:
        assert "首页" in client.get("/").text
        assert client.get("/assets/app.js").text == "console.log(1)"
        # 前端路由：未知页面路径返回首页
        assert "首页" in client.get("/threads/abc").text
        # 接口路径不兜底：仍然是 JSON 404
        missing = client.get("/api/not-exist")
        assert missing.status_code == 404
        assert missing.json() == {"detail": "Not Found"}
        assert client.get("/api/health").json() == {"status": "ok"}


def test_skips_frontend_when_not_built(tmp_path: Path) -> None:
    app = create_app(lifespan_handler=None, frontend_dist=tmp_path / "missing")
    with TestClient(app) as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/health").json() == {"status": "ok"}
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`LITELLM_LOCAL_MODEL_COST_MAP=True uv run pytest backend/tests/test_frontend.py -v`
预期：FAIL，`TypeError: create_app() got an unexpected keyword argument 'frontend_dist'`。

- [ ] **步骤 3：实现**

`backend/frontend.py`：

```python
"""正式使用时由后端直接提供打包好的前端页面（设计文档 13.5）。"""

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


class _SinglePageApp(StaticFiles):
    """找不到的页面路径返回前端首页，交给前端路由；/api 下的路径不兜底，保持 404。"""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or path.split("/", 1)[0] == "api":
                raise
            return await super().get_response("index.html", scope)


def mount_frontend(app: FastAPI, dist: Path) -> bool:
    """前端打包结果存在时挂载到 /；开发时没有打包结果就跳过（前端用 make web 单独运行）。"""
    if not (dist / "index.html").is_file():
        return False
    app.mount("/", _SinglePageApp(directory=dist, html=True), name="frontend")
    return True
```

`backend/main.py`（整个替换）：

```python
"""FastAPI 入口：启动时创建连接池、组装智能体与服务对象。"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from agents.main_agent.bootstrap import build_agent
from backend.api import api_router
from backend.api.deps import build_services
from backend.api.errors import install_error_handlers
from backend.frontend import FRONTEND_DIST, mount_frontend
from common.db import create_pool
from config import get_settings

type Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    pool = create_pool(settings.database_url)
    await pool.open()
    try:
        agent = await build_agent(settings, pool)
        services = build_services(settings, pool, agent)
        await services.runs.fail_unfinished()
        app.state.services = services
        yield
    finally:
        await pool.close()


def create_app(
    lifespan_handler: Lifespan | None = lifespan, frontend_dist: Path = FRONTEND_DIST
) -> FastAPI:
    app = FastAPI(title="open-personal-agent", lifespan=lifespan_handler)
    install_error_handlers(app)
    app.include_router(api_router, prefix="/api")
    mount_frontend(app, frontend_dist)  # 必须在接口路由之后挂载，否则会遮住 /api
    return app


app = create_app()
```

- [ ] **步骤 4：运行测试，确认通过**

运行同步骤 2。预期：2 passed；再运行 `make check-py`，预期全部通过（单元测试 25 个）。

- [ ] **步骤 5：多阶段镜像与启动配置**

`deploy/backend.Dockerfile`（整个替换）：

```dockerfile
# 第一阶段：打包前端（设计文档 13.5），依赖严格按 pnpm-lock.yaml 安装
FROM mirror.gcr.io/library/node:24.21.0-trixie-slim AS frontend
WORKDIR /frontend
RUN npm install --global pnpm@11.17.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/.npmrc ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# 第二阶段：后端（官方 uv 镜像，内含 Python 3.12），依赖严格按 uv.lock 安装
FROM ghcr.io/astral-sh/uv:0.11.7-python3.12-trixie-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    LITELLM_LOCAL_MODEL_COST_MAP=True

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev

COPY agents ./agents
COPY backend ./backend
COPY common ./common
COPY config ./config
COPY --from=frontend /frontend/dist ./frontend/dist

EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync alembic upgrade head && uv run --no-sync uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
```

`.dockerignore`（整个替换：带上前端源码，排除依赖与打包结果）：

```text
.venv
**/__pycache__
.mypy_cache
.ruff_cache
.pytest_cache
.import_linter_cache
.idea
.env
workdata
docs
frontend/node_modules
frontend/dist
```

`deploy/docker-compose.yml`（整个替换；变化只在 backend：不再整份读取 `.env`，只传需要的变量——修复 M8b）：

```yaml
# 所有第三方服务与本项目镜像统一在此定义（D13）。镜像版本全部固定。
# 当前网络访问不了 Docker Hub：Docker Hub 上的镜像经 Google 官方镜像站 mirror.gcr.io 拉取；
# 若该镜像站也不可用，把 mirror.gcr.io 换成 docker.1ms.run 再试。
name: open-personal-agent

services:
  postgres:
    image: mirror.gcr.io/pgvector/pgvector:0.8.7-pg18-trixie
    environment:
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: agent
      POSTGRES_DB: agent
    volumes:
      - pgdata:/var/lib/postgresql
      - ./postgres/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    ports: ["127.0.0.1:5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agent -d agent"]
      interval: 5s
      timeout: 5s
      retries: 20

  litellm:
    image: ghcr.io/berriai/litellm:v1.105.0
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    env_file: ../.env
    environment:
      DATABASE_URL: postgresql://agent:agent@postgres:5432/litellm
      LITELLM_LOCAL_MODEL_COST_MAP: "True"
      STORE_MODEL_IN_DB: "False"
    volumes:
      - ../config/models.yaml:/app/config.yaml:ro
    ports: ["127.0.0.1:4000:4000"]
    depends_on:
      postgres: { condition: service_healthy }
    healthcheck:
      # 镜像内没有 wget / curl，用自带的 python3 检查
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/health/liveliness')"]
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 30s

  ollama: # 只做向量化（D15），不跑对话模型
    image: mirror.gcr.io/ollama/ollama:0.40.3
    volumes:
      - ollama-models:/root/.ollama
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 5s
      timeout: 5s
      retries: 20

  ollama-init: # 一次性任务：拉取向量模型后退出（已存在时很快结束）
    image: mirror.gcr.io/ollama/ollama:0.40.3
    entrypoint: ["ollama"]
    command: ["pull", "qwen3-embedding:0.6b"]
    environment:
      OLLAMA_HOST: http://ollama:11434
    depends_on:
      ollama: { condition: service_healthy }
    restart: "no"

  backend:
    build:
      context: ..
      dockerfile: deploy/backend.Dockerfile
    # 开发模式：源码以目录挂载，改代码自动重载；启动前先执行数据库迁移
    command:
      - sh
      - -c
      - >-
        uv run --no-sync alembic upgrade head &&
        uv run --no-sync uvicorn backend.main:app --host 0.0.0.0 --port 8000
        --reload --reload-dir agents --reload-dir backend --reload-dir common --reload-dir config
    # 只传后端需要的变量（不把上游网关等其他密钥带进后端容器）；取值来自根目录 .env
    environment:
      DATABASE_URL: postgresql://agent:agent@postgres:5432/agent
      LITELLM_BASE_URL: http://litellm:4000
      LITELLM_MASTER_KEY: ${LITELLM_MASTER_KEY:?请在 .env 中设置 LITELLM_MASTER_KEY}
      LITELLM_LOCAL_MODEL_COST_MAP: "True"
      WORKDATA_DIR: /app/workdata
    volumes:
      - ../agents:/app/agents
      - ../backend:/app/backend
      - ../common:/app/common
      - ../config:/app/config
      - ../workdata:/app/workdata
    ports: ["127.0.0.1:8000:8000"]
    depends_on:
      postgres: { condition: service_healthy }
      litellm: { condition: service_healthy }
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"]
      interval: 5s
      timeout: 5s
      retries: 30
      start_period: 20s

  postgres-test: # 自动化测试专用：数据放内存盘，测完即弃
    profiles: [test]
    image: mirror.gcr.io/pgvector/pgvector:0.8.7-pg18-trixie
    environment:
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: agent
      POSTGRES_DB: agent_test
    tmpfs: [/var/lib/postgresql]
    ports: ["127.0.0.1:55432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agent -d agent_test"]
      interval: 2s
      timeout: 5s
      retries: 30

volumes:
  pgdata:
  ollama-models:
```

`Makefile`（整个替换；变化：`DC` 增加 `--env-file .env`，`up` 的说明）：

```makefile
# 常用命令入口。容器命令自动选择 docker compose 或 podman compose。
COMPOSE ?= $(shell command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 && echo "docker compose" || echo "podman compose")
# --env-file：compose 文件中的 ${变量} 取自根目录 .env
DC := $(COMPOSE) --env-file .env -f deploy/docker-compose.yml
# 使用项目内的空 Docker 配置：本机全局配置残留了 Docker Desktop 的凭据程序（credsStore=desktop），会导致构建失败
export DOCKER_CONFIG := $(CURDIR)/deploy/docker-config
export LITELLM_LOCAL_MODEL_COST_MAP := True
# 前端命令使用 frontend/.nvmrc 指定的 Node 版本（nvm 安装的那一份），不改动全局默认版本
NODE_VERSION := $(shell cat frontend/.nvmrc 2>/dev/null)
export PATH := $(HOME)/.nvm/versions/node/v$(NODE_VERSION)/bin:$(PATH)

.PHONY: install fmt check check-py check-web test test-int smoke \
	infra-up up down logs restart-gateway test-up test-down web migrate

install: ## 严格按锁文件安装前后端依赖
	uv sync --locked
	cd frontend && pnpm install --frozen-lockfile

fmt: ## 自动格式化
	uv run ruff format .
	uv run ruff check --fix .
	cd frontend && pnpm exec prettier --write .

check: check-py check-web ## 完成一个任务前必须通过：格式、类型、依赖方向、单元测试

check-py:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy .
	uv run lint-imports
	uv run pytest

check-web:
	cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm format && pnpm test

test: ## 只跑单元测试（不需要任何容器）
	uv run pytest

test-up: ## 启动测试专用数据库
	$(DC) --profile test up -d --wait postgres-test

test-down:
	$(DC) --profile test rm -sf postgres-test

test-int: test-up ## 集成测试（连接 postgres-test）
	uv run pytest -m integration

smoke: ## 先行验证：调用真实模型，会产生少量费用（需先 make infra-up）
	uv run pytest -m live -s agents/tests/live

infra-up: ## 启动数据库、网关、Ollama，并拉取向量模型
	$(DC) up -d --wait postgres litellm ollama
	$(DC) run --rm ollama-init

up: infra-up ## 一键启动全部服务，然后打开 http://127.0.0.1:8000（后端为开发模式，改代码自动重载）
	$(DC) up -d --build --wait backend

web: ## 本机启动前端开发服务器：http://127.0.0.1:5173
	cd frontend && pnpm dev

migrate: ## 在宿主机上对主库执行迁移（一般不需要，backend 启动时会自动执行）
	uv run alembic upgrade head

restart-gateway: ## 修改 config/models.yaml 后让网关重新加载
	$(DC) restart litellm

logs:
	$(DC) logs -f --tail=100

down: ## 停止所有服务（数据保留在数据卷中）
	$(DC) down
```

- [ ] **步骤 6：构建并一键启动**

运行：`make up`
预期：先拉取 `node:24.21.0-trixie-slim`（约 79MB），在镜像内安装前端依赖并打包，然后所有服务 healthy（首次约 5～10 分钟）。

```bash
curl -s http://127.0.0.1:8000/ | grep -o '<title>[^<]*</title>'
curl -s http://127.0.0.1:8000/threads/x | grep -o '<title>[^<]*</title>'
curl -s http://127.0.0.1:8000/api/health
curl -s -w ' HTTP %{http_code}\n' http://127.0.0.1:8000/api/nope
```
预期：前两行都是 `<title>个人智能体</title>`；`{"status":"ok"}`；`{"detail":"Not Found"} HTTP 404`。

- [ ] **步骤 7：检查点**

运行：`make check`
预期：全部通过。

---

### 任务 5：文档同步与端到端验证

**文件：**
- 修改：`docs/development/architecture.md`、`docs/development/coding-standards.md`、`docs/development/testing.md`、`README.md`、`CLAUDE.md`、`docs/decisions/README.md`、`docs/requirements/backlog.md`、`docs/changelog.md`
- 新建：`docs/decisions/D16-前端采用assistant-ui与主题系统.md`

- [ ] **步骤 1：规范文档**（三个文件整个替换）

`docs/development/architecture.md`（新增第 5 节"前端结构与设计系统"，其后各节顺延编号）：

````markdown
# 架构规范

> 适用于本项目全部代码。设计依据：`docs/specs/2026-10-10-personal-agent-design.md`。规范只在这里维护一份，`dev-standards` 技能只放要点并指向本文。

## 1. 总纲：底层解耦，功能内聚

- **底层解耦**：外部依赖（模型网关、沙箱、向量检索、文档解析、MCP、运行时队列等）都藏在我们自己定义的可替换接口后面；业务代码只认接口；"用哪个实现"只在组装根决定。
- **功能内聚**：一个能力模块把自己的接口、实现、数据访问、中间件、提供给智能体的工具放在一起；模块之间只调用对方公开的内容。
- **不过度包装**：LangChain 聊天模型、LangGraph 对话存档、deepagents 后端协议本身就是标准接口，直接使用。
- **只为基础设施建接口**：只有设计文档 4.1 所列的外部依赖才定义可替换接口，其他地方不预设抽象。

## 2. 三大块与依赖方向

```
frontend ──(HTTP 接口 + 推送协议)──→ backend ──→ agents ──→ config ──→ common
```

| 目录 | 职责 | 允许依赖 |
|---|---|---|
| `agents/` | 智能体能力；可脱离 HTTP 独立运行 | `config`、`common` |
| `backend/` | 把 agents 的能力通过 HTTP 与推送提供出去；运行调度 | `agents` 的公开内容、`config`、`common` |
| `frontend/` | 浏览器界面 | 只通过 `/api` 与推送协议访问 backend |
| `config/` | 读取配置的代码 + 所有可编辑的配置文件 | `common` |
| `common/` | 与业务无关的基础设施：数据库连接池、错误类型、ID | 无 |

依赖方向由 import-linter 强制（`pyproject.toml` 的 `[tool.importlinter]`），`make check` 会检查：
1. 分层：`backend → agents → config → common`，不得反向。
2. `backend` 不得引用 agents 的内部实现模块（如 `agents.main_agent.runtime.translator`），只用各模块 `__init__.py` 导出的内容。

## 3. 模块结构模板

### agents 能力模块（`agents/main_agent/<能力>/`）

| 文件 | 内容 |
|---|---|
| `__init__.py` | 对外公开的内容（其他模块与 backend 只能从这里导入） |
| `base.py` | 可替换接口（`typing.Protocol`）与数据结构（仅基础设施类能力需要） |
| `<实现名>.py` | 接口的具体实现，如 `litellm_proxy.py` |
| `tools.py` | 提供给智能体的工具 |
| `repo.py` | 本模块拥有的表的数据访问 |

`agents/main_agent/bootstrap.py` 是组装根：按 `config/app.yaml` 的 `adapters` 选择实现并装配，产出 `MainAgent`。

### backend 功能模块（`backend/<功能>/`）

| 文件 | 内容 |
|---|---|
| `schemas.py` | 接口与数据库之间的数据结构（pydantic） |
| `repo.py` | 数据访问（psycopg + 原生 SQL） |
| `manager.py` 等 | 业务流程 |
| `__init__.py` | 对外公开的内容 |

路由统一放在 `backend/api/`；服务对象在启动时装配到 `app.state.services`（见 `backend/api/deps.py`）。

## 4. 可替换接口的写法

```python
# agents/main_agent/<能力>/base.py —— 接口
class XxxGateway(Protocol):
    async def do(self, ...) -> Result: ...

# agents/main_agent/<能力>/<实现名>.py —— 实现（不继承接口，按结构匹配）
class FooXxxGateway:
    async def do(self, ...) -> Result: ...

# agents/main_agent/bootstrap.py —— 登记
_XXX: dict[str, Callable[[Settings], XxxGateway]] = {"foo": lambda s: FooXxxGateway(...)}

# agents/tests/contracts/test_xxx_contract.py —— 契约测试
IMPLEMENTATIONS = [make_foo]          # 新实现加进这个列表，必须跑通同一套测试
```

新增实现 = 写实现类 + 在组装根登记 + 加进契约测试 + 在 `config/app.yaml` 选中。

## 5. 前端结构与设计系统（设计文档 13 节）

| 目录 | 职责 |
|---|---|
| `src/themes/` | 主题即数据：`types.ts`（主题结构）、`default.ts`（默认主题深浅两版）、`registry.ts`（登记表）、`apply.ts`（写到根节点的 CSS 变量）、`mode.ts`（深浅色偏好）、`ThemeProvider.tsx` |
| `src/styles/` | `tokens.css`：主题变量 → 派生色（color-mix）→ Tailwind 语义样式类；`markdown.css`：回答排版 |
| `src/components/chat/` | **唯一**使用 assistant-ui 的地方：转换函数 `adapter.ts`、消息与工具卡片 `parts.tsx`、对话区 `ChatThread.tsx`；对外只导出 `ChatThread` |
| `src/features/<功能>/` | 业务功能：会话列表、对话页、模型选择、外观设置等，只用语义样式类和 `components/chat` 的导出 |
| `src/layout/` | 整体布局（左侧会话栏 + 右侧对话区） |
| `src/api/` | 接口调用、推送订阅、查询配置、类型 |

规则（由检查自动保证）：
1. 组件只用语义样式类（`bg-background`、`bg-card`、`text-foreground`、`text-muted-foreground`、`border-border`、`bg-primary` 等），不写具体颜色——`src/styles/no-raw-colors.test.ts`。
2. 主题必须提供全部必需字段，且与 `tokens.css` 的首屏默认值一致——`src/themes/themes.test.ts`。
3. 只有 `src/components/chat/` 可以引用 `@assistant-ui/*`——ESLint `no-restricted-imports`。
4. 新增主题：在 `src/themes/` 加一个主题文件并在 `registry.ts` 登记，组件不改。

## 6. 数据归属与迁移

- 每张表归属一个模块，只有该模块的 `repo.py` 读写它。
- 表结构变更统一用 Alembic，脚本放 `backend/migrations/versions/`，**一律写原生 SQL**；文件名带归属模块前缀，如 `0002_agents_knowledge.py`。
- deepagents 的对话存档表由 `AsyncPostgresSaver.setup()` 自行创建，不写迁移。
- 所有表带 `user_id`（v1 固定 `'me'`）。

## 7. 配置、密钥与第三方服务

- 可编辑配置都在 `config/`：`app.yaml`（应用）、`models.yaml`（网关模型版本清单）。
- 密钥只放根目录 `.env`（不进版本库）；模板是 `.env.example`。
- **第三方服务一律在 `deploy/docker-compose.yml` 中定义**，镜像写死版本；当前网络访问不了 Docker Hub，经 `mirror.gcr.io` 拉取。
- 个人数据放 `workdata/`（不进版本库、需要备份）；数据库数据在 Docker 数据卷中。

## 8. 新增功能的步骤清单

**新增 agents 能力模块**：建 `agents/main_agent/<能力>/` → 需要外部依赖时先写 `base.py` 接口与契约测试 → 写实现 → 在 `bootstrap.py` 装配 → 只通过 `__init__.py` 对外公开 → 如需建表，按第 6 节写迁移。

**新增接口路由**：在对应 backend 功能模块写 `schemas.py` / `repo.py` / 业务 → 在 `backend/api/` 加路由 → 可预期错误抛 `common.errors` 中的类型（统一映射为 404 / 409 / 503）→ 流式接口的存在性检查放在依赖里（推送开始后无法再返回 404）。

**新增前端功能**：在 `frontend/src/features/<功能>/` 下建组件，只用语义样式类；涉及对话展示的改动放在 `src/components/chat/`；接口调用加到 `src/api/client.ts`；类型加到 `src/api/types.ts`；纯逻辑（如事件处理器、转换函数）必须有单元测试。

**新增第三方服务**：加进 `deploy/docker-compose.yml`（固定版本、只监听 `127.0.0.1`）→ 在 `Makefile` 补命令 → 写决策记录。
````

`docs/development/coding-standards.md`（第 3 节补充前端样式规则）：

```markdown
# 编码规范

> 以官方规范为准，代码尽量精简，与项目架构对齐（见 `architecture.md`）。

## 1. 通用

- 注释、文档字符串、文档用**中文**；代码标识符用**英文**。
- 注释只解释"为什么"，不复述代码；不留无用代码、不留注释掉的代码。
- 函数短小、职责单一；不为"以后可能"写代码。
- 优先用标准库和已选框架的原生能力，不引入功能重叠的新依赖。

## 2. Python

- 依据：PEP 8（风格）、PEP 257（文档字符串）、PEP 484 与 typing 官方文档（类型）。
- 工具：`ruff format` 统一格式；`ruff check` 规则见 `pyproject.toml`；`mypy --strict`（含 pydantic 插件）。行宽 100。
- **所有输入输出操作一律异步**（数据库、HTTP、模型调用）。
- **边界数据一律用 pydantic 定义**：接口请求 / 响应、事件、配置。
- 可预期错误使用 `common.errors`（`NotFoundError` / `ConflictError` / `UpstreamError`）；不用裸 `except`。唯一允许捕获宽泛异常的地方是"运行边界"（把任何失败转成 `run.finished(failed)`），必须写 `# noqa: BLE001` 并注明原因。
- SQL：一律参数化（`%s`）；f-string 只能拼接常量列名，绝不拼接外部输入。
- FastAPI：按官方写法用 `APIRouter`、`Depends`、`lifespan`；推送用 `fastapi.sse.EventSourceResponse`（官方 SSE 支持），不额外引入 sse 库。
- LangChain / LangGraph / deepagents：按官方 API 使用；deepagents 只能出现在 `agents/main_agent/runtime/`。
- 命名：模块与函数 `snake_case`，类 `PascalCase`，常量 `UPPER_CASE`；不使用会遮蔽内置名的方法名（如 `list`）。

## 3. TypeScript / React

- TypeScript 严格模式（`tsconfig.json`）；禁止非空断言 `!`（ESLint `typescript-eslint` strict）。
- 遵循官方"React 规则"与 Hooks 规则（`eslint-plugin-react-hooks` 推荐配置）：不要在 effect 里同步 setState 来派生状态——用 `key` 重建组件或在渲染时计算。
- 接口调用集中在 `src/api/`；类型集中在 `src/api/types.ts`（M1b 起改为自动生成）。
- **样式只用语义样式类**（见架构规范第 5 节），不写 `bg-blue-600`、`#1a2b3c`、`rgba(...)` 这类具体颜色；颜色、字体、圆角只在 `src/themes/` 与 `src/styles/` 中定义。
- 图标统一用 `lucide-react`。
- assistant-ui 只在 `src/components/chat/` 中使用。
- Prettier 统一格式（行宽 100）。

## 4. 依赖与版本（D12）

- Python：`uv add 包名==版本`（直接依赖一律精确版本）；安装 `uv sync --locked`。
- 前端：`pnpm add -E 包名@版本`（`.npmrc` 已设 `save-exact=true`）；安装 `pnpm install --frozen-lockfile`。
- pnpm 11 会拒绝"发布时间太短"的版本；遇到时改选更早的稳定版本，不要放宽策略。
- 升级依赖要在 `docs/changelog.md` 记录原因；避开 litellm 1.82.7 / 1.82.8（曾被投毒）。

## 5. 文档同步（完成定义的一部分）

一个功能做到以下三点才算完成：
1. 更新 `docs/requirements/backlog.md` 的状态（较大功能另写 `docs/requirements/YYYY-MM-DD-<功能>.md`）；
2. 涉及架构取舍时，在 `docs/decisions/` 补决策记录；
3. 在 `docs/changelog.md` 记一笔。

（提交信息规范"约定式提交"待建立 git 仓库后启用。）
```

`docs/development/testing.md`（补充主题检查）：

```markdown
# 测试规范

## 1. 分层与命令

| 层次 | 标记 | 命令 | 需要什么 |
|---|---|---|---|
| 单元测试（含契约测试、离线先行验证） | 无 | `make test`（`make check` 也会跑） | 什么都不需要 |
| 集成测试 | `@pytest.mark.integration` | `make test-int` | 自动启动 compose `test` 配置组的 `postgres-test`（端口 55432） |
| 真实模型冒烟测试 | `@pytest.mark.live` | `make smoke` | `make infra-up` + `.env` 中的模型密钥；会产生少量费用 |
| 前端单元测试 | — | `cd frontend && pnpm test` | 什么都不需要 |

默认 `pytest` 只跑单元测试（`pyproject.toml` 的 `addopts` 排除了 integration 与 live）。

## 2. 写测试的规则

- 先写测试、看它失败，再写实现。
- **不调用真实模型**：用 `agents/tests/fakes.py` 里的 `ScriptedChatModel`（按剧本回复，支持工具调用与逐字流式）、`FailingChatModel`、`FakeGateway`。LangChain 自带的 `GenericFakeChatModel` 在流式模式下不支持工具调用，不要用。
- **契约测试**：每个可替换接口在 `agents/tests/contracts/` 下有一套测试，用 `IMPLEMENTATIONS` 列表参数化；新实现必须加进列表并跑通。
- **数据库测试**：使用根目录 `conftest.py` 的 `db` 夹具（每个测试前清空 backend 的表）；不要连接开发库。
- **接口测试**：使用 `backend/tests/conftest.py` 的 `make_client(模型)`，它直接装配服务对象，不走 `lifespan`。
- **离线先行验证**放在 `agents/tests/spikes/`：用于固定"第三方库的关键行为"，库升级后它们会第一时间报警。
- 前端：纯逻辑（如 `features/chat/reducer.ts`、`components/chat/adapter.ts`）必须有 Vitest 单元测试；事件序列用接近真实的样例。
- 前端设计系统有两条自动检查：主题契约（`src/themes/themes.test.ts`）与写死颜色检查（`src/styles/no-raw-colors.test.ts`），改动主题或组件后它们必须通过。

## 3. 完成一个任务前

`make check` 全部通过；涉及数据库的改动还要 `make test-int` 通过。
```

- [ ] **步骤 2：决策记录**

`docs/decisions/D16-前端采用assistant-ui与主题系统.md`：

```markdown
# D16：前端对话组件采用 assistant-ui，样式由本项目主题系统决定

- 状态：已采纳
- 日期：2026-10-13

## 背景

M0 的前端是手写组件，样式写死颜色、观感简陋；用户希望界面美观（参考 Hermes Agent 的深色科技感），并且"一套前端代码，按主题切换样式"。

## 备选方案

1. 继续手写组件，只换样式。
2. 采用 assistant-ui（React 对话组件库，支持对接自己的后端）。
3. 直接改造开源界面（OpenClaw 为 Lit 技术栈，Hermes 为 React 但与其后端耦合，deep-agents-ui 对接 LangGraph 官方服务器）。

## 结论

- 对话组件采用 assistant-ui，只用不带样式的基础组件，经"外部数据源"接法对接本项目的事件处理器；只在 `frontend/src/components/chat/` 一层使用，版本写死。
- 样式由本项目主题系统决定：主题即数据 → CSS 变量（由背景色与主色派生）→ 语义样式类；默认主题参考 Hermes Teal，深浅两版。
- 布局参考 Hermes 的聊天页，智能体专属面板参考 deep-agents-ui。

## 原因与代价

- 2026-10-13 一次性验证：与本项目 React 19 / Vite 8 / Tailwind 4 / 严格类型检查兼容；流式回答、工具卡片、错误、停止正常；切换主题无需改组件；自带中文输入法处理；为思考过程、子智能体、审批、附件预留了数据结构。
- 代价：打包体积增加约 110KB（压缩后）；assistant-ui 尚未到 1.0，升级时接口可能变化——通过版本写死与"只在一层使用"控制影响面。
```

`docs/decisions/README.md`（整个替换）：

````markdown
# 架构决策记录

每个重要决定一份记录，文件名 `Dxx-<简短标题>.md`，编号与设计文档第 3 节一致；新决策顺延编号。先行验证等阶段性结论用 `Mx-<标题>.md`。

## 模板

```markdown
# Dxx：<决策标题>

- 状态：已采纳 / 已替代（被 Dyy 替代）
- 日期：YYYY-MM-DD

## 背景
## 备选方案
## 结论
## 原因与代价
```

## 索引

| 编号 | 标题 | 状态 |
|---|---|---|
| D01～D15 | 见设计文档第 3 节（M1b 逐条补成独立记录） | 已采纳 |
| D16 | [前端采用 assistant-ui 与主题系统](D16-前端采用assistant-ui与主题系统.md) | 已采纳 |
| M0 | [先行验证结论](M0-先行验证结论.md)（M0 任务 14 产出） | — |
````

- [ ] **步骤 3：使用说明**

`README.md`（整个替换）：

````markdown
# open_personal_agent

自建的通用个人助理：多轮对话、统一知识库与长期记忆、隔离环境里执行代码、通过 MCP 接入外部工具，按会话切换各家大模型的具体版本。

## 首次准备（只做一次）

前提：Podman（或 Docker）、uv、nvm 安装的 Node 24.21.0 与 pnpm 11.17.0。

```bash
cp .env.example .env      # 然后填写 LITELLM_MASTER_KEY（sk- 开头的随机串）与 UPSTREAM_GATEWAY_KEY
make install              # 严格按锁文件安装 Python 与前端依赖
```

## 日常启动

```bash
podman machine start      # 电脑重启后需要；已在运行会提示 already running
make up                   # 一键启动：数据库、模型网关、Ollama、后端（含打包好的前端）
```

然后打开 http://127.0.0.1:8000 。停止：`make down`（数据保留）。

开发前端时可另开终端运行 `make web`，打开 http://127.0.0.1:5173（改代码即时生效，接口转发到 8000）。

## 文档

见 [docs/README.md](docs/README.md)。
````

`CLAUDE.md`（整个替换）：

```markdown
# open_personal_agent

个人智能体：deepagents + LiteLLM 网关 + PostgreSQL + FastAPI + React。设计文档：`docs/specs/2026-10-10-personal-agent-design.md`。

**开发、修改、审查任何代码前，先加载 `dev-standards` 技能**（`.claude/skills/dev-standards/SKILL.md`）。

## 常用命令

| 命令 | 作用 |
|---|---|
| `make install` | 严格按锁文件安装前后端依赖 |
| `make infra-up` | 启动数据库、网关、Ollama，并拉取向量模型 |
| `make up` | 一键启动全部服务，然后打开 http://127.0.0.1:8000 |
| `make web` | 前端开发服务器 http://127.0.0.1:5173（改代码即时生效） |
| `make check` | 格式、类型、依赖方向、前后端单元测试 |
| `make test-int` | 集成测试（自动启动测试数据库） |
| `make smoke` | 真实模型先行验证（会产生少量费用） |
| `make down` | 停止所有服务 |

## 约定

- 用中文交流与写文档；代码标识符用英文。
- 当前是纯本地项目，没有 git 仓库：不要执行 git 命令。
- 一个功能完成 = `make check` 通过 + backlog / changelog 已更新（见 `docs/development/coding-standards.md` 第 5 节）。
```

- [ ] **步骤 4：浏览器端到端验证**（`make up` 已运行，打开 http://127.0.0.1:8000）

1. 首次打开即为深色（或与系统一致），**刷新时不闪白**。
2. 左下角外观切换：点"浅色"立即变为暖白背景；刷新后仍为浅色；点"跟随系统"后与系统设置一致。
3. 点"新会话"，发送"用一个小表格对比 Python 和 TypeScript 的三个特点"：回答逐字出现，表格带边框，自动滚动到最新内容；左侧标题与**顶栏标题**都变为首条消息（M5）。
4. 发送"用 write_file 把 hello 写入 /notes.txt，再用 read_file 读回来"：出现两张可展开的工具卡片，状态从"运行中"变为"完成"。
5. 切到其他会话再切回：对话完整；鼠标移到回答上出现"复制"按钮，可复制。
6. 运行 `podman stop open-personal-agent-backend-1` 后发送一条消息：只出现红色错误提示，不留下用户消息，**输入框里仍是原文**；运行 `podman start open-personal-agent-backend-1` 后点发送按钮重试成功。
7. 在第 6 步后端停止期间刷新页面：顶栏模型选择处显示"模型列表加载失败，正在重试…"；后端恢复后约 5 秒内自动出现模型列表，无需刷新。
8. 中文输入法输入时按回车选字：只确认候选词，不发送。

预期：以上全部符合描述。

- [ ] **步骤 5：需求池与变更记录**

`docs/requirements/backlog.md`（整个替换；完成后把 R04a 的状态改为"完成"）：

```markdown
# 需求池

状态：待定 / 计划 / 进行中 / 完成。优先级：高 / 中 / 低。

| 编号 | 需求 | 所属期 | 优先级 | 状态 |
|---|---|---|---|---|
| R01 | 开发规范、项目技能、文档骨架 | M0 | 高 | 完成 |
| R02 | 浏览器中与任一模型版本多轮对话（最小端到端链路） | M0 | 高 | 完成 |
| R03 | 先行验证 V1～V6 | M0 | 高 | 完成（V6 批量速度不达标，已决定先接受） |
| R04a | 前端改版（主题系统、assistant-ui 对话层、新布局）与一键启动 | M1a | 高 | 进行中 |
| R04b | 取消、深度思考与子智能体展示、用量统计、事件分批写库、本机安全防护、前端类型自动生成 | M1b | 高 | 计划 |
| R05 | 沙箱执行代码、文件上传下载与产物预览、数据分析员子智能体 | M2 | 高 | 计划 |
| R06 | 统一知识库（文档 + 记忆 + 常驻条目） | M3 | 高 | 计划 |
| R07 | MCP 接入、审批暂停与恢复、预算刹车 | M4 | 高 | 计划 |
| R08 | 用量统计页、备份命令、端到端测试、使用指南 | M5 | 中 | 计划 |
| R09 | 联网搜索与网页阅读（MCP） | 扩展阶段 1 | 中 | 待定 |
| R10 | 本地对话模型（宿主机原生运行） | 扩展阶段 1 | 低 | 待定 |
| R11 | 向量模型改用云端（1024 维，替换本地 Ollama 以加快文档入库） | 待定 | 中 | 待定 |
```

`docs/changelog.md`（整个替换；完成后把小节标题改为"### M1a 前端改版与一键启动（完成）"）：

```markdown
# 变更记录

## 未发布

### M1a 前端改版与一键启动（进行中）

- 新增：前端设计系统——主题即数据、CSS 变量派生色、默认主题深浅两版（参考 Hermes Agent），外观可切换跟随系统 / 深色 / 浅色。
- 新增：对话区改用 assistant-ui（只在 `components/chat/` 使用），新布局（左侧会话栏 + 右侧对话区）。
- 新增：一键启动——backend 镜像内含打包好的前端，`make up` 后打开 http://127.0.0.1:8000。
- 修复：422 错误显示为 [object Object]；顶栏标题不随首条消息更新；模型列表加载失败后不自动重试；旧版 Safari 输入法回车（由 assistant-ui 处理）；后端容器只接收需要的环境变量。

### M0 首跑（完成）

- 新增：开发规范（架构 / 编码 / 测试）、`dev-standards` 项目技能、文档骨架。
- 新增：Python 项目骨架（uv，直接依赖精确版本）、配置包、公共包、docker compose 基础服务。
- 新增：最小端到端对话（agents 运行入口与事件协议、backend 会话 / 运行 / 推送、前端对话界面）。
- 新增：backend 镜像与一键启动（make up / make web）；模型来源接入公司 LiteLLM 网关（claude-opus-4-6、gemini-3.5-flash、gpt-5.5-pro）。
- 修复（独立审查）：切回会话丢对话；运行中途重启后前端无限重连且不显示原因；超过保留期续传丢字；落库失败时推送不结束；发送失败留下幽灵消息。
- 完成：先行验证 V1～V6，结论见 docs/decisions/M0-先行验证结论.md（V6 批量向量化速度不达标，待决定方案）。
```

- [ ] **步骤 6：检查点**

运行：`make check`，再运行 `make test-int`
预期：全部通过（集成测试 20 个，本计划未改动其覆盖的代码）。

---

## 自查记录（写计划时完成）

- **设计覆盖（第 13 节、D16、第 21 节 M1 的前端部分）：** 13.1 技术选型与 assistant-ui 接入方式 → 任务 1、2；13.2 主题系统、默认主题、深浅色、两条自动检查 → 任务 1、3；13.3 布局 → 任务 3；13.4 转换函数 → 任务 2；13.5 一键启动 → 任务 4；M0 延后的次要问题 M4、M5、M7、M8b、M9 → 任务 3、4；D16 决策记录 → 任务 5。M3（停机回收任务）、M6（片段 ID 兜底）属后端，放入 M1b。
- **与设计文档的差异：** 设计文档第 21 节把 M1 作为一期；为便于审阅与执行拆为 M1a（本计划）与 M1b，内容不变。
- **占位扫描：** 无"待定 / 以后实现"类步骤。
- **类型与命名一致性：** `ChatThread` / `onSend: (text) => Promise<boolean>`、`toThreadMessages`、`historyQuery` / `threadsQuery` / `modelsQuery` / `retryWhileFailing`、`errorMessage`、`ThreadList.onSelect(threadId)`、`create_app(..., frontend_dist=...)`、`mount_frontend` 在定义处与使用处一致（已用严格类型检查与 mypy 验证）。
