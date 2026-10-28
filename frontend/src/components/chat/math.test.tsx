import Markdown from "react-markdown";
import { renderToStaticMarkup } from "react-dom/server";
import remarkGfm from "remark-gfm";
import { describe, expect, it } from "vitest";
import { MATH_REHYPE_PLUGINS, MATH_REMARK_PLUGINS, normalizeMath } from "./math";

function render(text: string): string {
  return renderToStaticMarkup(
    <Markdown
      remarkPlugins={[remarkGfm, ...MATH_REMARK_PLUGINS]}
      rehypePlugins={MATH_REHYPE_PLUGINS}
    >
      {normalizeMath(text)}
    </Markdown>,
  );
}

const count = (html: string, needle: string) => html.split(needle).length - 1;
/** 公式个数（行内与公式块都算）、公式块个数、报错个数 */
const formulas = (html: string) => count(html, 'class="katex"');
const blocks = (html: string) => count(html, 'class="katex-display"');
const errors = (html: string) => count(html, "katex-error");

describe("normalizeMath：代码里的内容一律不动", () => {
  it.each([
    ["行内代码", "用 `echo $HOME` 查看 `\\(x\\)`"],
    ["根层的代码块", "```bash\nprice=$5\necho \\(x\\)\n```\n"],
    ["还没写完的代码块（正在逐字输出）", "```python\nprint('$5')"],
    ["列表里缩进的代码块", "1. 安装\n    ```bash\n    export PATH=$HOME/bin:$PATH\n    ```\n"],
    ["列表里还没写完的代码块", '1. 安装\n     ```bash\n     echo "费用 $5"\n'],
    ["列表里的 ~~~ 代码块", "- 例子\n    ~~~sh\n    echo $HOME $USER\n    ~~~\n"],
    ["引用里的代码块", "> ```sh\n> echo $HOME/$USER\n> ```\n"],
    ["缩进 4 格的代码块", "示例：\n\n    price=$5; echo $price/$total\n\n结束"],
    ["HTML 块", "<div>\n$5 and $x$\n</div>\n"],
  ])("%s", (_, text) => {
    expect(normalizeMath(text)).toBe(text);
  });
});

describe("公式的写法", () => {
  it("\\(…\\) 是行内公式，单独一行的 \\[…\\] 与 $$…$$ 是公式块", () => {
    const html = render("质能方程 \\(E=mc^2\\)\n\n\\[\\frac{a}{b}\\]\n\n$$x^2$$");
    expect(formulas(html)).toBe(3);
    expect(blocks(html)).toBe(2);
  });

  it("句中的 $$…$$ 仍是行内公式", () => {
    const html = render("因为 $$a+b$$ 所以");
    expect(formulas(html)).toBe(1);
    expect(blocks(html)).toBe(0);
  });

  it("列表里的公式块留在列表项里，列表不被拆开", () => {
    const html = render(
      "1. **面积**：\n   \\[\n   S = \\pi r^2\n   \\]\n2. **周长**：\n   \\[\n   C = 2\\pi r\n   \\]\n",
    );
    expect(count(html, "<ol")).toBe(1);
    expect(count(html, "<li>")).toBe(2);
    expect(blocks(html)).toBe(2);
    expect(errors(html)).toBe(0);
  });

  it("引用里的公式留在引用里", () => {
    const html = render("> 定理：\\[ a^2+b^2=c^2 \\]\n> 证明略");
    expect(count(html, "<blockquote>")).toBe(1);
    expect(formulas(html)).toBe(1);
    expect(html).toMatch(/<blockquote>[\s\S]*katex[\s\S]*证明略[\s\S]*<\/blockquote>/);
  });

  it("表格里的公式不拆散表格", () => {
    const html = render(
      "| 名称 | 公式 |\n|---|---|\n| 面积 | \\[S=\\pi r^2\\] |\n| 周长 | \\(C=2\\pi r\\) |",
    );
    expect(count(html, "<tr>")).toBe(3);
    expect(formulas(html)).toBe(2);
  });

  it("\\(…\\) 里写 \\$ 也是一整个公式", () => {
    const html = render("总价为 \\( 3 \\times \\$5 = \\$15 \\)。");
    expect(formulas(html)).toBe(1);
    expect(errors(html)).toBe(0);
    expect(html).toContain("。</p>");
  });

  it("写错的公式显示原文（危险色），不影响其余内容", () => {
    const html = render("错的 $\\frac{a$ 后面照常");
    expect(errors(html)).toBe(1);
    expect(html).toContain("var(--color-danger)");
    expect(html).toContain("后面照常");
  });
});

describe("金额里的 $ 照常是文字", () => {
  it.each([
    ["价格 $5 到 $10", "价格 $5 到 $10"],
    ["本次花费 $2.08，累计 $13.5。", "本次花费 $2.08，累计 $13.5。"],
    ["$5-$10", "$5-$10"],
  ])("%s", (text, shown) => {
    const html = render(text);
    expect(formulas(html)).toBe(0);
    expect(html).toContain(shown);
  });

  it.each([
    ["中文里不带空格", "成本是$5，其中变量$x$表示数量", "成本是$5，其中变量"],
    ["全角标点", "总价：$5。单价：$x$。", "总价：$5。单价："],
    ["同一段的两行", "单价：$3\n数量：$n$ 个", "单价：$3"],
    ["列表的两项", "- 单价：$3\n- 数量：$n$ 个", "单价：$3"],
    ["表格的两行", "|项目|值|\n|---|---|\n|单价|$3|\n|数量|$n$|", "$3"],
  ])("金额与公式混在一起：%s", (_, text, shown) => {
    const html = render(text);
    expect(formulas(html)).toBe(1);
    expect(errors(html)).toBe(0);
    expect(html).toContain(shown);
  });
});

describe("躲开框架误判的几种写法（积压小问题 A12～A17）", () => {
  const PLACEHOLDERS = /[\uE000-\uF8FF]/u;

  it("正文里的 \\[1\\]、a\\[0\\] 是文字", () => {
    const html = render("见文献 \\[1\\]，数组 a\\[0\\] 是第一项");
    expect(formulas(html)).toBe(0);
    expect(html).toContain("[1]");
    expect(html).toContain("a[0]");
  });

  it("单独一行的 \\[…\\] 公式照旧是公式块", () => {
    expect(blocks(render("面积：\n\\[\nS = \\pi r^2\n\\]\n"))).toBe(1);
  });

  it("公式块里的 \\\\[2pt] 不和后面的 \\[…\\] 配对", () => {
    const html = render(
      "$$\n\\begin{aligned} a &= 1 \\\\[2pt] b &= 2 \\end{aligned}\n$$\n\n再看 \\[x^2\\]",
    );
    expect(formulas(html)).toBe(2);
    expect(errors(html)).toBe(0);
  });

  it("裸地址与 <…> 自动链接里的 $数字 不插反斜杠", () => {
    for (const text of ["看 https://example.com/a$1b", "看 <https://example.com/a$1b>"]) {
      const html = render(text);
      expect(html).toContain('href="https://example.com/a$1b"');
      expect(html).not.toContain("\\$");
    }
  });

  it.each([
    ["链接后紧跟两个金额", "在[携程](https://a.com)上，机票$120，酒店$80", 0, "机票$120，酒店$80"],
    [
      "链接后接金额与公式",
      "详见[文档](https://a.com)，成本是$5，其中变量$x$",
      1,
      "成本是$5，其中变量",
    ],
    ["公式里的网址后接金额", "$\\text{https://a.com}$ 价格$5，变量$x$", 2, "价格$5，变量"],
  ])("网址后面同一行的金额照常是文字：%s", (_, text, count, shown) => {
    const html = render(text);
    expect(formulas(html)).toBe(count);
    expect(errors(html)).toBe(0);
    expect(html).toContain(shown);
  });

  it("原文里本来就有占位用的私用区字符时原样保留，代码里也不改", () => {
    const text = "图标  与价格 $5\n\n```sh\nicon=\n```\n";
    expect(normalizeMath(text)).toBe(text.replace("$5", "\\$5"));
  });

  it("正文的 $HOME/$USER 是文字，$AB/BC$ 仍是公式", () => {
    const path = render("把文件放到 $HOME/$USER 目录下");
    expect(formulas(path)).toBe(0);
    expect(path).toContain("$HOME/$USER");
    expect(formulas(render("比例 $AB/BC$ 不变"))).toBe(1);
  });

  it("设 $n$2 个不报错，价格 $x 和 $5 仍不是公式", () => {
    const html = render("设 $n$2 个");
    expect(formulas(html)).toBe(1);
    expect(errors(html)).toBe(0);
    expect(formulas(render("价格 $x 和 $5"))).toBe(0);
  });

  it("公式里的尺寸被限住", () => {
    const html = render("$\\rule{100000em}{1em}$");
    // 公式原文（annotation）里照样有 100000em；画出来的宽度被限成 20em
    expect(html).not.toMatch(/width[:=]\s*"?100000em/);
    expect(html).toContain('width="20em"');
  });

  it("最终的页面上没有占位字符", () => {
    for (const text of [
      "见文献 \\[1\\]，数组 a\\[0\\]",
      "$$a \\\\[2pt] b$$ 和 \\[x\\]",
      "看 https://example.com/a$1b",
      "设 $n$2 个",
    ]) {
      expect(render(text)).not.toMatch(PLACEHOLDERS);
    }
  });
});
