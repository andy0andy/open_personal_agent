import type { ComponentPropsWithoutRef } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CODE_COLLAPSE_LINES, CodeBlock, CodeHeader } from "./code";
import { MessageRunningContext } from "./messageContext";

const Pre = (props: ComponentPropsWithoutRef<"pre">) => <pre {...props} />;
const Code = (props: ComponentPropsWithoutRef<"code">) => <code {...props} />;

describe("代码块", () => {
  it("认得的语言：按语法着色", () => {
    const html = renderToStaticMarkup(
      <CodeBlock components={{ Pre, Code }} language="python" code="def f(): pass" />,
    );
    expect(html).toContain('<span class="hljs-keyword">def</span>');
  });

  it("不认得的语言：原样显示，特殊字符照常转义", () => {
    const html = renderToStaticMarkup(
      <CodeBlock components={{ Pre, Code }} language="klingon" code="x < y" />,
    );
    expect(html).toContain("x &lt; y");
    expect(html).not.toContain("hljs-");
  });

  it("标题栏：显示语言名与复制按钮；没写语言时显示“代码”", () => {
    const html = renderToStaticMarkup(<CodeHeader language="python" code="x" />);
    expect(html).toContain("python");
    expect(html).toContain('aria-label="复制代码"');
    expect(renderToStaticMarkup(<CodeHeader language="" code="x" />)).toContain("代码");
  });

  it("超过 16 行先折叠，下面一个“展开全部 N 行”", () => {
    const lines = (count: number) => Array.from({ length: count }, (_, i) => `x = ${i}`).join("\n");
    expect(CODE_COLLAPSE_LINES).toBe(16);
    const long = renderToStaticMarkup(
      <CodeBlock components={{ Pre, Code }} language="python" code={lines(20)} />,
    );
    expect(long).toContain("展开全部 20 行");
    const short = renderToStaticMarkup(
      <CodeBlock components={{ Pre, Code }} language="python" code={lines(16)} />,
    );
    expect(short).not.toContain("展开全部");
  });

  it("回答还在输出时不着色，结束后再着色", () => {
    const html = renderToStaticMarkup(
      <MessageRunningContext value={true}>
        <CodeBlock components={{ Pre, Code }} language="python" code="def f(): pass" />
      </MessageRunningContext>,
    );
    expect(html).toContain("def f(): pass");
    expect(html).not.toContain("hljs-");
  });
});
