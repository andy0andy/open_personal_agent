import { common, createLowlight } from "lowlight";

/** 常用的 37 种语言（D19）；颜色由 styles/markdown.css 按 hljs- 类名从主题变量派生。 */
const lowlight = createLowlight(common);

export type HighlightTree = ReturnType<typeof lowlight.highlight>;

/** 代码着色：认得的语言（含常见简称，不分大小写）返回着色后的片段，否则 null（照原样显示）。 */
export function highlight(code: string, language: string): HighlightTree | null {
  const name = language.trim().toLowerCase();
  if (!name || !lowlight.registered(name)) return null;
  try {
    return lowlight.highlight(name, code);
  } catch {
    return null; // 着色库内部出错：照原样显示，不能让整个回答白屏
  }
}
