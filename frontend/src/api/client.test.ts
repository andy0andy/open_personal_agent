import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, errorMessage, fileContentUrl, readableError } from "./client";

// 本机令牌另在 session.test.ts 里测；这里只看请求本身
vi.mock("./session", () => ({
  ensureToken: vi.fn(async () => "t1"),
  refreshToken: vi.fn(async () => "t1"),
}));

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

describe("网络与错误文案", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("后端连不上时给出中文提示，而不是浏览器的原始报错", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    await expect(api.listThreads()).rejects.toThrow("无法连接到后端，请确认服务已启动");
  });

  it("显示错误时只取错误信息本身，不带 Error: 前缀", () => {
    expect(readableError(new Error("请求失败：502"))).toBe("请求失败：502");
    expect(readableError("其他错误")).toBe("其他错误");
  });
});

describe("会话改名与排序", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("保存顺序返回 204（没有内容）时正常结束，不去解析响应体", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.reorderThreads(["a", "b"])).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/threads/order",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ thread_ids: ["a", "b"] }) }),
    );
  });

  it("改会话：只提交要改的几项（标题、模型、审批权限）", async () => {
    const thread = { id: "a", title: "新名字" };
    const fetchMock = vi.fn(async () => Response.json(thread));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.updateThread("a", { title: "新名字" })).resolves.toEqual(thread);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/threads/a",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ title: "新名字" }) }),
    );
    await api.updateThread("a", { permission_mode: "skip" });
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/threads/a",
      expect.objectContaining({ body: JSON.stringify({ permission_mode: "skip" }) }),
    );
  });
});

describe("删除会话", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("发送删除请求，204 时正常结束", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.deleteThread("a")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/threads/a",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});

describe("ApiError", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("出错时抛出 ApiError，带上状态码与后端给的原因", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ detail: "该会话已有进行中的运行" }, { status: 409 })),
    );
    const error: unknown = await api.listThreads().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect(readableError(error)).toBe("该会话已有进行中的运行");
  });
});

describe("fileContentUrl", () => {
  it("默认在页面里打开；download 为真时作为附件下载", () => {
    expect(fileContentUrl("t1", "f1", false)).toBe("/api/threads/t1/files/f1/content");
    expect(fileContentUrl("t1", "f1", true)).toBe("/api/threads/t1/files/f1/content?download=1");
  });
});

describe("会话文件", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("表格预览按工作表名取数据，名字经过编码", async () => {
    const preview = { sheets: ["明细"], sheet: "明细", rows: [["a"]], truncated: false };
    const fetchMock = vi.fn(async () => Response.json(preview));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.tablePreview("t1", "f1", "明细")).resolves.toEqual(preview);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/threads/t1/files/f1/table?sheet=%E6%98%8E%E7%BB%86",
      expect.anything(),
    );
    await api.tablePreview("t1", "f1", null);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/threads/t1/files/f1/table", expect.anything());
  });

  it("读取文件原文；文件已不在时给出后端的说明", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("# 标题", { headers: { "content-type": "text/markdown" } })),
    );
    await expect(api.fileText("t1", "f1")).resolves.toBe("# 标题");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ detail: "文件已不存在" }, { status: 404 })),
    );
    await expect(api.fileText("t1", "f1")).rejects.toThrow("文件已不存在");
  });
});

describe("上传与附件", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("上传：请求体就是文件，文件名编码后放在 X-File-Name 请求头", async () => {
    const fetchMock = vi.fn(async () => Response.json({ id: "f1" }, { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["a,b"], "销售 数据.csv", { type: "text/csv" });
    await expect(api.uploadFile("t1", file)).resolves.toEqual({ id: "f1" });
    expect(fetchMock).toHaveBeenCalledWith("/api/threads/t1/files", {
      method: "POST",
      body: file,
      headers: {
        "Content-Type": "text/csv",
        "X-File-Name": "%E9%94%80%E5%94%AE%20%E6%95%B0%E6%8D%AE.csv",
        "X-Session-Token": "t1",
      },
    });
    await api.uploadFile("t1", new File(["x"], "data"));
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/threads/t1/files",
      expect.objectContaining({
        headers: {
          "Content-Type": "application/octet-stream",
          "X-File-Name": "data",
          "X-Session-Token": "t1",
        },
      }),
    );
  });

  it("上传文档到知识库：请求体就是文件，文件名编码后放在 X-File-Name", async () => {
    const fetchMock = vi.fn(async () => Response.json({ id: "d1" }, { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["x"], "员工 手册.docx", { type: "" });
    await expect(api.uploadDocument(file)).resolves.toEqual({ id: "d1" });
    expect(fetchMock).toHaveBeenCalledWith("/api/knowledge/documents", {
      method: "POST",
      body: file,
      headers: {
        "Content-Type": "application/octet-stream",
        "X-File-Name": encodeURIComponent("员工 手册.docx"),
        "X-Session-Token": "t1",
      },
    });
  });

  it("发消息时带上附件的文件 ID；模型取会话上的，不随消息发", async () => {
    const fetchMock = vi.fn(async () => Response.json({ id: "r1" }, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    await api.startRun("t1", "看看", ["f1"]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/threads/t1/runs",
      expect.objectContaining({
        body: JSON.stringify({ message: "看看", attachments: ["f1"] }),
      }),
    );
  });
});

describe("上传可以中途取消（积压小问题 D6）", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("上传把 signal 交给 fetch；取消时原样抛出，不说成连不上后端", async () => {
    const seen: (AbortSignal | null | undefined)[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_: string, init?: RequestInit) => {
        seen.push(init?.signal);
        throw new DOMException("aborted", "AbortError");
      }),
    );
    const controller = new AbortController();
    controller.abort();
    const upload = api.uploadFile("t1", new File(["x"], "a.txt"), controller.signal);
    await expect(upload).rejects.toThrow("aborted");
    expect(seen).toEqual([controller.signal]);
  });
});
