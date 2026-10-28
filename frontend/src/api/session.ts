/**
 * 本机令牌（设计 2026-10-23 5.11，D25）：页面先向后端取一次，之后每个接口请求都在请求头里带上；
 * 取令牌时后端同时下发同值的 Cookie，推送、图片、下载这类带不了请求头的请求靠它。
 * 后端每次启动换一个令牌：遇到 401 时 refreshToken 重取，页面不用刷新。
 */
let current: Promise<string> | null = null;

/** 当前的令牌：还没取过（或上次没取到）时去取。 */
export function ensureToken(): Promise<string> {
  return current ?? load();
}

/** 重取令牌（后端重启后旧的对不上了）。 */
export function refreshToken(): Promise<string> {
  return load();
}

function load(): Promise<string> {
  const pending = fetchToken();
  current = pending;
  // 没取到就忘掉，下一次请求重新去取
  pending.catch(() => {
    if (current === pending) current = null;
  });
  return pending;
}

async function fetchToken(): Promise<string> {
  let resp: Response;
  try {
    resp = await fetch("/api/session");
  } catch {
    throw new Error("无法连接到后端，请确认服务已启动");
  }
  if (!resp.ok) throw new Error(`请求失败：${resp.status}`);
  return ((await resp.json()) as { token: string }).token;
}

/** 能重新加载的图片：浏览器里的 <img>，单测里用替身 */
interface ReloadableImage {
  src: string;
  dataset: Record<string, string | undefined>;
}

/**
 * 图片带不了请求头，靠 Cookie：后端重启后 Cookie 里的令牌旧了，图片就加载失败（积压小问题 E4）。
 * 失败时重取一次令牌（同时换新 Cookie），给地址加个参数让浏览器重新请求；每张图只重试一次。
 * 记下重试用的地址而不是"重试过"：换图时 React 复用同一个 <img>，换上的新图失败了也要重试。
 */
export async function reloadImageOnce(img: ReloadableImage): Promise<void> {
  if (img.dataset.retried === img.src) return;
  const retry = `${img.src}${img.src.includes("?") ? "&" : "?"}r=${Date.now()}`;
  img.dataset.retried = retry;
  await refreshToken().catch(() => undefined);
  img.src = retry;
  img.dataset.retried = img.src; // 浏览器读回来的是完整地址
}

/** 下载链接同样靠 Cookie：点的时候先换一次令牌再下载，后端重启过也不会下到"令牌不对"的页面。 */
export async function downloadWithFreshSession(url: string, name: string): Promise<void> {
  await refreshToken().catch(() => undefined);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
}
