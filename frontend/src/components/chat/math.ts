import { escapeCurrencyDollars, normalizeMathDelimiters } from "@assistant-ui/react-markdown";
import { fromMarkdown } from "mdast-util-from-markdown";
import type { Options } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkMath from "remark-math";

type PluggableList = NonNullable<Options["remarkPlugins"]>;

/** Markdown 语法树里用到的部分（mdast） */
type MdNode = {
  type: string;
  value?: string;
  position?: { start: { offset?: number }; end: { offset?: number } };
  children?: MdNode[];
  [key: string]: unknown;
};

/**
 * 渲染前统一公式写法（D19）。以 assistant-ui 自带的两个函数为主：\(…\)、\[…\] 转成 $ 写法（带上列表、
 * 引用的前缀），金额里的 $ 转义成文字，代码一律不动。先补上它们处理不好的几种写法（见 patchProse）：
 * 要躲开框架处理的字符先换成占位字符，框架处理完再换回来。
 */
export function normalizeMath(text: string): string {
  // 原文里本来就有占位字符（如图标字体的码位）时不用占位，免得换回时把它们也改掉
  if (HAS_HELD.test(text)) return escapeCurrencyDollars(normalizeMathDelimiters(text));
  return restore(escapeCurrencyDollars(normalizeMathDelimiters(patchProse(text))));
}

// 占位字符（私用区，正常文字里不会出现）：框架看不见它们，处理完原样换回
const HOLD = { lb: "\uE001", rb: "\uE002", lp: "\uE003", rp: "\uE004", dollar: "\uE005" };
const RESTORE: Record<string, string> = {
  [HOLD.lb]: "\\[",
  [HOLD.rb]: "\\]",
  [HOLD.lp]: "\\(",
  [HOLD.rp]: "\\)",
  [HOLD.dollar]: "$",
};
const HELD = /[\uE001-\uE005]/gu;
const HAS_HELD = /[\uE001-\uE005]/u; // \u4E0D\u5E26 g\uFF1A\u5E26 g \u7684 test \u4F1A\u8BB0\u4F4F\u4E0A\u6B21\u5339\u914D\u7684\u4F4D\u7F6E

function restore(text: string): string {
  return text.replace(HELD, (held) => RESTORE[held] ?? held);
}

/** 只改代码以外的部分：代码的位置由真正的 Markdown 解析得出（各种缩进、引用里的代码块、HTML 块都算）。 */
function patchProse(text: string): string {
  if (!text.includes("$") && !text.includes("\\[")) return text;
  let out = "";
  let last = 0;
  for (const [start, end] of codeRanges(text)) {
    out += patchSegment(text.slice(last, start)) + text.slice(start, end);
    last = end;
  }
  return out + patchSegment(text.slice(last));
}

const CODE_NODES = new Set(["code", "inlineCode", "html"]);

function codeRanges(text: string): [number, number][] {
  const ranges: [number, number][] = [];
  const walk = (node: MdNode) => {
    const start = node.position?.start.offset;
    const end = node.position?.end.offset;
    if (CODE_NODES.has(node.type) && start !== undefined && end !== undefined) {
      ranges.push([start, end]);
    } else {
      node.children?.forEach(walk);
    }
  };
  walk(fromMarkdown(text) as unknown as MdNode);
  return ranges;
}

function patchSegment(text: string): string {
  return escapeAmbiguousAmounts(holdLiteralBrackets(holdLinkDollars(dollarBodiesToDouble(text))));
}

/**
 * 正文里像引用编号、下标的 \[…\]（"文献 \[1\]"、"a\[0\]"）是文字：框架会一律当成公式块。
 * 认这两种：括号里只有数字、逗号、连字符；或 \[ 紧挨在字母数字后面。同一行内。
 */
function holdLiteralBrackets(text: string): string {
  return text.replace(/\\\[([^\n\\]*?)\\\]/g, (match, body: string, at: number) =>
    /^[\d,\s-]+$/.test(body) || /[A-Za-z0-9]/.test(text.charAt(at - 1))
      ? `${HOLD.lb}${body}${HOLD.rb}`
      : match,
  );
}

/**
 * 网址里的 $（裸网址、<…> 自动链接）：框架与下面的金额规则都会往里插反斜杠，链接就坏了。
 * Markdown 链接的地址 "](…)" 先整段跳过（那里的 \$ 由 Markdown 当转义，href 本来就对），裸网址到
 * { } 为止（公式里的 \text{…}）：中文里常不带空格，否则会把后面同一行的金额一起吞进"网址"。
 */
function holdLinkDollars(text: string): string {
  return text.replace(/\]\([^)\s]*\)|<https?:\/\/[^\s>]+>|https?:\/\/[^\s<>{}]+/g, (url) =>
    url.startsWith("](") ? url : url.replaceAll("$", HOLD.dollar),
  );
}

/** $$…$$ 公式块里的 \[ \] \( \)（如换行写法 \\[2pt]）：框架会把它和后面别处的 \] 配成一对 */
function holdDelimiters(math: string): string {
  return math
    .replaceAll("\\[", HOLD.lb)
    .replaceAll("\\]", HOLD.rb)
    .replaceAll("\\(", HOLD.lp)
    .replaceAll("\\)", HOLD.rp);
}

/**
 * \(…\) 里写了 \$ 时转成 $$…$$：单个 $ 的公式遇到 $ 就结束（反斜杠挡不住），框架转出的 $…$ 会报错。
 * 不跨段落。
 */
function dollarBodiesToDouble(text: string): string {
  return text.replace(/\\\(([\s\S]+?)\\\)/g, (match, body: string) =>
    body.includes("$") && !/\n[ \t]*\n/.test(body) ? `$$${body.trim()}$$` : match,
  );
}

/** 汉字与全角标点：公式里几乎不会出现，金额后面的中文里却到处都是 */
const CJK = /[\p{Script=Han}\u3000-\u303f\uff00-\uffef]/u;

/**
 * 框架只在"像不像公式"上判断 $ 后跟数字的情况，中文里不带空格的写法会判断错：
 * "成本是$5，其中变量$x$" 被当成公式 "5，其中变量"，真正的公式反而落单报错。这里先转义这类金额：
 * $ 后跟数字，且同一行里没有下一个 $、两者之间夹着中文，或下一个 $ 后面紧跟数字（"$5-$10"）。
 * 已经打开的公式的结尾 $ 不转义；$$…$$ 跳过（只藏起里面的 \[ 一类）。
 * 另外两种：路径里的环境变量（"$HOME/$USER"）是文字；"设 $n$2 个"这种结尾 $ 后紧跟数字的，
 * 框架会把"$2"当金额转义，公式就断了，结尾的 $ 先换成占位字符。
 */
function escapeAmbiguousAmounts(text: string): string {
  let out = "";
  let open = false;
  let openAt = 0;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text.charAt(i);
    if (ch === "\\") {
      out += text.slice(i, i + 2);
      i += 1;
    } else if (ch === "\n") {
      open = false;
      out += ch;
    } else if (ch !== "$") {
      out += ch;
    } else if (text.charAt(i + 1) === "$") {
      const end = text.indexOf("$$", i + 2);
      const stop = end === -1 ? text.length : end + 2;
      out += holdDelimiters(text.slice(i, stop));
      i = stop - 1;
    } else if (open) {
      open = false;
      const body = text.slice(openAt + 1, i);
      out += /\d/.test(text.charAt(i + 1)) && isFormulaBody(body) ? HOLD.dollar : ch;
    } else if (/^[A-Z_]{3,}\//.test(text.slice(i + 1, i + 64))) {
      out += "\\$";
    } else if (/\d/.test(text.charAt(i + 1)) && looksLikeAmount(text, i)) {
      out += "\\$";
    } else {
      open = true;
      openAt = i;
      out += ch;
    }
  }
  return out;
}

/** 像公式的内容：非空、两头不是空白、不夹汉字（"价格 $x 和 $5" 里的 "x 和 " 不算） */
function isFormulaBody(body: string): boolean {
  return body !== "" && !/^\s|\s$/.test(body) && !CJK.test(body);
}

function looksLikeAmount(text: string, dollar: number): boolean {
  const lineEnd = text.indexOf("\n", dollar);
  const rest = text.slice(dollar + 1, lineEnd === -1 ? undefined : lineEnd);
  const close = rest.indexOf("$");
  return close === -1 || CJK.test(rest.slice(0, close)) || /\d/.test(rest.charAt(close + 1));
}

/**
 * 单独占一行的 $$…$$ 按公式块显示。框架把单行的 \[…\] 转成 $$…$$，remark-math 把它当行内公式，
 * 分数、积分号会变小；在列表项、引用里也一样，拆出来的公式块留在原处。
 */
function remarkStandaloneDisplayMath() {
  return (tree: MdNode, file: { value: unknown }) => {
    promote(tree, String(file.value));
  };
}

function promote(parent: MdNode, source: string): void {
  if (!parent.children) return;
  parent.children = parent.children.flatMap((child) =>
    child.type === "paragraph" ? splitParagraph(child, source) : [child],
  );
  parent.children.forEach((child) => promote(child, source));
}

function splitParagraph(paragraph: MdNode, source: string): MdNode[] {
  const children = paragraph.children ?? [];
  const standalone = (node: MdNode, index: number) =>
    node.type === "inlineMath" &&
    source.startsWith("$$", node.position?.start.offset ?? -1) &&
    endsLine(children[index - 1], /\n[ \t]*$/) &&
    endsLine(children[index + 1], /^[ \t]*\n/);
  if (!children.some(standalone)) return [paragraph];

  const result: MdNode[] = [];
  let buffer: MdNode[] = [];
  const flush = () => {
    const kept = trimEdges(buffer);
    if (kept.length > 0) result.push({ type: "paragraph", children: kept });
    buffer = [];
  };
  children.forEach((node, index) => {
    if (standalone(node, index)) {
      flush();
      result.push(displayMath(node));
    } else {
      buffer.push(node);
    }
  });
  flush();
  return result;
}

/** 相邻的是行首 / 行尾：没有相邻节点、硬换行，或文字在这一侧以换行结束 */
function endsLine(node: MdNode | undefined, edge: RegExp): boolean {
  return (
    node === undefined ||
    node.type === "break" ||
    (node.type === "text" && edge.test(node.value ?? ""))
  );
}

function trimEdges(nodes: MdNode[]): MdNode[] {
  const trimmed = nodes.map((node, index) => {
    if (node.type !== "text") return node;
    let value = node.value ?? "";
    if (index === 0) value = value.replace(/^[ \t]*\n/, "");
    if (index === nodes.length - 1) value = value.replace(/\n[ \t]*$/, "");
    return { ...node, value };
  });
  return trimmed.filter((node) => node.type !== "text" || node.value !== "");
}

/** 与 remark-math 解析出的公式块相同的结构（mdast-util-math），rehype-katex 按 math-display 渲染 */
function displayMath(node: MdNode): MdNode {
  const value = node.value ?? "";
  return {
    type: "math",
    meta: null,
    value,
    position: node.position,
    data: {
      hName: "pre",
      hChildren: [
        {
          type: "element",
          tagName: "code",
          properties: { className: ["language-math", "math-display"] },
          children: [{ type: "text", value }],
        },
      ],
    },
  };
}

/** 回答里的数学公式（D19）：remark-math 识别 $…$ 与 $$…$$，KaTeX 渲染；写错的公式显示原文。 */
export const MATH_REMARK_PLUGINS: PluggableList = [remarkMath, remarkStandaloneDisplayMath];
export const MATH_REHYPE_PLUGINS: PluggableList = [
  [
    rehypeKatex,
    // maxSize：公式里写的尺寸最多 20em（被注入的 \rule{100000em} 一类不会撑出极长的元素）
    { throwOnError: false, errorColor: "var(--color-danger)", strict: "ignore", maxSize: 20 },
  ],
];
