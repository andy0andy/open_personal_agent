import { afterEach, describe, expect, it, vi } from "vitest";
import { copyText } from "./useCopy";

/** 退路用的隐藏文本框：只记下内容与是否被选中、移除。 */
function fakeDocument(copyWorks: boolean) {
  const area = { value: "", style: {}, setAttribute: vi.fn(), select: vi.fn(), remove: vi.fn() };
  const execCommand = vi.fn(() => {
    if (!copyWorks) throw new Error("不支持");
    return true;
  });
  vi.stubGlobal("document", {
    createElement: () => area,
    body: { appendChild: vi.fn() },
    execCommand,
  });
  return { area, execCommand };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("copyText：复制文字", () => {
  it("浏览器提供剪贴板接口时用它", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    expect(await copyText("def f(): pass")).toBe(true);
    expect(writeText).toHaveBeenCalledWith("def f(): pass");
  });

  it("没有剪贴板接口时（非安全环境）退回到隐藏文本框复制", async () => {
    vi.stubGlobal("navigator", {});
    const { area, execCommand } = fakeDocument(true);
    expect(await copyText("echo $HOME")).toBe(true);
    expect(area.value).toBe("echo $HOME");
    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(area.remove).toHaveBeenCalled();
  });

  it("剪贴板接口被拒绝时也退回到隐藏文本框", async () => {
    vi.stubGlobal("navigator", {
      clipboard: { writeText: () => Promise.reject(new Error("没有权限")) },
    });
    const { execCommand } = fakeDocument(true);
    expect(await copyText("x")).toBe(true);
    expect(execCommand).toHaveBeenCalledWith("copy");
  });

  it("两种办法都不行时返回 false（界面显示复制失败）", async () => {
    vi.stubGlobal("navigator", {});
    const { area } = fakeDocument(false);
    expect(await copyText("x")).toBe(false);
    expect(area.remove).toHaveBeenCalled();
  });
});
