/**
 * 输入框草稿（设计 2026-10-22 3.10）：按会话存在浏览器本地，切走再回来还在，发送成功后清掉。
 * 浏览器不让用本地存储（隐私模式等）时不保存，但输入照常。
 */
const key = (threadId: string) => `opa.draft.${threadId}`;

export function loadDraft(threadId: string): string {
  try {
    return localStorage.getItem(key(threadId)) ?? "";
  } catch {
    return "";
  }
}

/** 空文本（含只有空白）即删除。 */
export function saveDraft(threadId: string, text: string): void {
  try {
    if (text.trim() === "") localStorage.removeItem(key(threadId));
    else localStorage.setItem(key(threadId), text);
  } catch {
    // 记不住也不影响输入
  }
}

export function clearDraft(threadId: string): void {
  saveDraft(threadId, "");
}

/**
 * 输入停下 delay 毫秒后才保存草稿（不每打一个字就写一次本地存储）；flush 把还没来得及保存的
 * 立即存上（离开会话时）。
 */
export function draftSaver(threadId: string, delay = 400) {
  let latest: string | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  return {
    update(text: string): void {
      if (text === latest) return;
      latest = text;
      clearTimeout(timer);
      timer = setTimeout(() => {
        saveDraft(threadId, text);
        latest = null;
      }, delay);
    },
    flush(): void {
      clearTimeout(timer);
      if (latest !== null) saveDraft(threadId, latest);
      latest = null;
    },
  };
}
