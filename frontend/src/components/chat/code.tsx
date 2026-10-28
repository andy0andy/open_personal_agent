import type { CodeHeaderProps, SyntaxHighlighterProps } from "@assistant-ui/react-markdown";
import { toJsxRuntime } from "hast-util-to-jsx-runtime";
import { Check, ChevronDown, ChevronUp, Copy } from "lucide-react";
import { useContext, useMemo, useState } from "react";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
import { useCopy } from "../useCopy";
import { highlight } from "./highlight";
import { MessageRunningContext } from "./messageContext";

/** 超过这么多行的代码块先折叠（设计 2026-10-22 3.9）。 */
export const CODE_COLLAPSE_LINES = 16;

/**
 * 回答里的代码块（D19）：assistant-ui 交来原文与语言，按语法着色；认不得的语言原样显示。
 * 回答还在输出时不着色；超过 16 行先折叠，下面一个"展开全部 N 行"。
 */
export function CodeBlock({ components: { Pre, Code }, language, code }: SyntaxHighlighterProps) {
  const running = useContext(MessageRunningContext);
  const [expanded, setExpanded] = useState(false);
  const content = useMemo(() => {
    const tree = running ? null : highlight(code, language);
    return tree === null ? code : toJsxRuntime(tree, { Fragment, jsx, jsxs });
  }, [code, language, running]);
  const lines = code.replace(/\n$/, "").split("\n").length;
  const collapsible = lines > CODE_COLLAPSE_LINES;
  return (
    // 折叠时按行高限高（样式见 markdown.css 的 .code-collapsed）
    <Pre className={collapsible && !expanded ? "code-collapsed" : undefined}>
      <Code className="hljs">{content}</Code>
      {collapsible && (
        <button
          type="button"
          aria-expanded={expanded}
          className="code-toggle mt-2 flex items-center gap-1 font-sans text-xs text-muted-foreground hover:text-foreground"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? (
            <ChevronUp aria-hidden="true" className="size-3.5" />
          ) : (
            <ChevronDown aria-hidden="true" className="size-3.5" />
          )}
          {expanded ? "收起" : `展开全部 ${lines} 行`}
        </button>
      )}
    </Pre>
  );
}

/** 代码块上方的标题栏：语言名与复制按钮。 */
export function CodeHeader({ language, code }: CodeHeaderProps) {
  const { state, copy } = useCopy();
  return (
    <div className="code-header flex items-center justify-between gap-2 px-3 py-1 text-xs text-muted-foreground">
      <span className="font-mono">{language || "代码"}</span>
      <button
        type="button"
        className="-mr-1 flex items-center gap-1 rounded-md p-1 hover:bg-accent hover:text-foreground"
        aria-label="复制代码"
        title="复制代码"
        onClick={() => copy(code)}
      >
        {state === "copied" ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        {state === "copied" && "已复制"}
        {state === "failed" && <span className="text-danger">复制失败</span>}
      </button>
    </div>
  );
}
