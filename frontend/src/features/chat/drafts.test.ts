import { afterEach, describe, expect, it, vi } from "vitest";
import { clearDraft, draftSaver, loadDraft, saveDraft } from "./drafts";

function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, value),
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("输入框草稿（按会话保存在浏览器里）", () => {
  it("存了能读回来，各会话互不影响", () => {
    vi.stubGlobal("localStorage", memoryStorage());
    saveDraft("t1", "写一半的话");
    expect(loadDraft("t1")).toBe("写一半的话");
    expect(loadDraft("t2")).toBe("");
    expect(localStorage.getItem("opa.draft.t1")).toBe("写一半的话");
  });

  it("空文本即删除；发送成功后清掉", () => {
    vi.stubGlobal("localStorage", memoryStorage());
    saveDraft("t1", "草稿");
    saveDraft("t1", "  ");
    expect(localStorage.getItem("opa.draft.t1")).toBeNull();
    saveDraft("t1", "草稿");
    clearDraft("t1");
    expect(loadDraft("t1")).toBe("");
  });

  it("浏览器不让用本地存储（隐私模式）：不保存，也不报错", () => {
    const broken = memoryStorage();
    broken.getItem = () => {
      throw new Error("SecurityError");
    };
    broken.setItem = () => {
      throw new Error("QuotaExceededError");
    };
    vi.stubGlobal("localStorage", broken);
    expect(() => saveDraft("t1", "草稿")).not.toThrow();
    expect(loadDraft("t1")).toBe("");
  });
});

describe("输入停下才保存草稿（积压小问题 I15）", () => {
  it("停 400ms 才保存；离开会话时把没来得及保存的补存上", () => {
    vi.useFakeTimers();
    try {
      vi.stubGlobal("localStorage", memoryStorage());
      const saver = draftSaver("t1");
      saver.update("写");
      saver.update("写一半");
      vi.advanceTimersByTime(399);
      expect(loadDraft("t1")).toBe("");
      vi.advanceTimersByTime(1);
      expect(loadDraft("t1")).toBe("写一半");
      saver.update("写一半的话");
      saver.flush(); // 离开会话：不等 400ms
      expect(loadDraft("t1")).toBe("写一半的话");
    } finally {
      vi.useRealTimers();
    }
  });
});
