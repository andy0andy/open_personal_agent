import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const UNAUTHORIZED = { detail: "会话令牌不对或已过期，请刷新页面" };

/** 记下每个请求的地址与带的令牌；/api/session 依次发 t1、t2…，valid 决定哪个令牌有效。 */
function backend(valid: (token: string | null) => boolean) {
  const calls: string[] = [];
  let issued = 0;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const token = new Headers(init?.headers).get("X-Session-Token");
    calls.push(token ? `${url} ${token}` : url);
    if (url === "/api/session") {
      issued += 1;
      return Response.json({ token: `t${issued}` });
    }
    return valid(token) ? Response.json([]) : Response.json(UNAUTHORIZED, { status: 401 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

describe("本机令牌（设计 2026-10-23 5.11）", () => {
  beforeEach(() => {
    vi.resetModules(); // 令牌缓存在模块里：每个测试从头取
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("先取一次令牌，之后每个接口请求都带在请求头里", async () => {
    const calls = backend((token) => token === "t1");
    const { api } = await import("./client");
    await api.listThreads();
    await api.listModels();
    expect(calls).toEqual(["/api/session", "/api/threads t1", "/api/models t1"]);
  });

  it("401（后端重启、令牌换了）时重取一次令牌再试，页面不用刷新", async () => {
    const calls = backend((token) => token === "t2");
    const { api } = await import("./client");
    await expect(api.listThreads()).resolves.toEqual([]);
    expect(calls).toEqual(["/api/session", "/api/threads t1", "/api/session", "/api/threads t2"]);
  });

  it("重取令牌后还是 401：只重试这一次，给出后端的说明", async () => {
    const calls = backend(() => false);
    const { api } = await import("./client");
    await expect(api.listThreads()).rejects.toThrow("会话令牌不对或已过期，请刷新页面");
    expect(calls).toEqual(["/api/session", "/api/threads t1", "/api/session", "/api/threads t2"]);
  });

  it("后端连不上时取令牌也给中文提示；恢复后重新去取", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    const { api } = await import("./client");
    await expect(api.listThreads()).rejects.toThrow("无法连接到后端，请确认服务已启动");
    const calls = backend((token) => token === "t1");
    await expect(api.listThreads()).resolves.toEqual([]);
    expect(calls).toEqual(["/api/session", "/api/threads t1"]);
  });
});

describe("后端重启后的图片与下载（积压小问题 E4）", () => {
  beforeEach(() => {
    vi.resetModules();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("图片加载失败时重取一次令牌、换地址重载；再失败不再重试", async () => {
    const calls = backend(() => true);
    const { reloadImageOnce } = await import("./session");
    const img = { src: "/api/threads/t/files/f", dataset: {} as Record<string, string> };
    await reloadImageOnce(img);
    expect(calls).toEqual(["/api/session"]);
    expect(img.src).toMatch(/^\/api\/threads\/t\/files\/f\?r=\d+$/);
    const reloaded = img.src;
    await reloadImageOnce(img);
    expect(calls).toEqual(["/api/session"]);
    expect(img.src).toBe(reloaded);
  });

  it("同一个元素换成另一张图后再失败，照样重试一次（审查 Minor 7）", async () => {
    const calls = backend(() => true);
    const { reloadImageOnce } = await import("./session");
    const img = { src: "/api/threads/t/files/a", dataset: {} as Record<string, string> };
    await reloadImageOnce(img);
    img.src = "/api/threads/t/files/b"; // 文件预览换图时 React 复用同一个 <img>
    await reloadImageOnce(img);
    expect(calls).toEqual(["/api/session", "/api/session"]);
    expect(img.src).toMatch(/^\/api\/threads\/t\/files\/b\?r=\d+$/);
  });

  it("下载前先换一次令牌（同时换新 Cookie）再下载", async () => {
    const calls = backend(() => true);
    const clicked: string[] = [];
    vi.stubGlobal("document", {
      createElement: () => {
        const link = {
          href: "",
          download: "",
          click: () => clicked.push(`${link.href} ${link.download}`),
        };
        return link;
      },
    });
    const { downloadWithFreshSession } = await import("./session");
    await downloadWithFreshSession("/api/threads/t/files/f?download=1", "报表.xlsx");
    expect(calls).toEqual(["/api/session"]);
    expect(clicked).toEqual(["/api/threads/t/files/f?download=1 报表.xlsx"]);
  });
});
