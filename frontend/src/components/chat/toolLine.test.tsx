import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ToolLine, failedCount, runningLabel } from "./toolLine";

const done = { type: "complete" } as const;

describe("工具行", () => {
  it("很长的命令只占一行：摘要可以截断", () => {
    const html = renderToStaticMarkup(
      <ToolLine
        toolName="execute"
        args={{ command: "x".repeat(500) }}
        status={done}
        result={"ok\n[Command succeeded with exit code 0]"}
        isError={false}
      />,
    );
    expect(html).toMatch(/<span class="[^"]*min-w-0[^"]*truncate[^"]*"[^>]*>x{500}<\/span>/);
  });

  it("执行命令展开后是 $ 命令、退出码与输出，不再显示参数 JSON", () => {
    const html = renderToStaticMarkup(
      <ToolLine
        toolName="execute"
        args={{ command: "python a.py" }}
        status={done}
        result={"合计 3\n[Command failed with exit code 2]"}
        isError={false}
      />,
    );
    expect(html).toContain("执行命令");
    expect(html).toContain("python a.py");
    expect(html).toContain("退出码 2");
    expect(html).toContain("合计 3");
    expect(html).not.toContain("[Command failed");
    expect(html).not.toContain('"command"');
  });

  it("成功不写“完成”，有起止时间时显示用时", () => {
    const html = renderToStaticMarkup(
      <ToolLine
        toolName="read_file"
        args={{ file_path: "/skills/excel/SKILL.md" }}
        status={done}
        result="内容"
        isError={false}
        artifact={{
          waiting: false,
          startedAt: "2026-10-22T08:00:00.000Z",
          finishedAt: "2026-10-22T08:00:01.200Z",
        }}
      />,
    );
    expect(html).toContain("读取文件");
    expect(html).toContain("1.2 秒");
    expect(html).not.toContain("完成");
  });

  it("等过审批的不显示用时（含等你的时间）", () => {
    const html = renderToStaticMarkup(
      <ToolLine
        toolName="read_file"
        args={{ file_path: "/a" }}
        status={done}
        result="内容"
        isError={false}
        artifact={{
          waiting: false,
          waited: true,
          startedAt: "2026-10-22T08:00:00.000Z",
          finishedAt: "2026-10-22T08:03:00.000Z",
        }}
      />,
    );
    expect(html).not.toContain("3 分");
  });

  it("等过审批、有真正开始执行的时间时，用时从它算起", () => {
    const html = renderToStaticMarkup(
      <ToolLine
        toolName="read_file"
        args={{ file_path: "/a" }}
        status={done}
        result="内容"
        isError={false}
        artifact={{
          waiting: false,
          waited: true,
          startedAt: "2026-10-22T08:00:00.000Z",
          runningAt: "2026-10-22T08:02:58.800Z",
          finishedAt: "2026-10-22T08:03:00.000Z",
        }}
      />,
    );
    expect(html).toContain("1.2 秒");
    expect(html).not.toContain("3 分");
  });

  it("失败显示“出错”", () => {
    const html = renderToStaticMarkup(
      <ToolLine toolName="ls" args={{ path: "/" }} status={done} result="没有权限" isError />,
    );
    expect(html).toContain("出错");
  });

  it("处理过的审批：显示决定；修改后执行的参数不用点开就看得到", () => {
    const html = renderToStaticMarkup(
      <ToolLine
        toolName="demo_add_note"
        args={{ text: "买牛奶" }}
        status={done}
        result="好了"
        isError={false}
        artifact={{
          waiting: false,
          waited: true,
          decision: {
            label: "已修改参数后执行",
            tone: "success",
            editedArgs: { text: "买豆浆" },
          },
        }}
      />,
    );
    expect(html).toContain("已修改参数后执行");
    expect(html.indexOf("修改后的参数（实际执行的）")).toBeGreaterThan(html.indexOf("</details>"));
    expect(html).toContain("买豆浆");
  });

  it("拒绝的不再另写“出错”", () => {
    const html = renderToStaticMarkup(
      <ToolLine
        toolName="execute"
        args={{ command: "rm x" }}
        status={done}
        result="rejected"
        isError
        artifact={{ waiting: false, waited: true, decision: { label: "已拒绝", tone: "danger" } }}
      />,
    );
    expect(html).toContain("已拒绝");
    expect(html).not.toContain("出错");
  });

  it("命令失败（退出码不是 0）收起时也看得出来；成功的不写退出码", () => {
    const line = (result: string) => {
      const html = renderToStaticMarkup(
        <ToolLine
          toolName="execute"
          args={{ command: "pytest" }}
          status={done}
          result={result}
          isError={false}
        />,
      );
      return html.slice(html.indexOf("<summary"), html.indexOf("</summary>"));
    };
    expect(line("FAILED\n[Command failed with exit code 1]")).toContain("退出码 1");
    expect(line("ok\n[Command succeeded with exit code 0]")).not.toContain("退出码");
  });

  it("工具组的出错数不算拒绝、回复、停止的（它们本来就没执行）", () => {
    const tool = (isError: boolean, tone?: "success" | "danger" | "muted") => ({
      toolName: "execute",
      args: {},
      status: done,
      result: "x",
      isError,
      ...(tone ? { artifact: { waiting: false, decision: { label: "决定", tone } } } : {}),
    });
    expect(
      failedCount([tool(true, "danger"), tool(true, "muted"), tool(true), tool(true, "success")]),
    ).toBe(2);
    expect(failedCount([tool(false)])).toBe(0);
  });

  it("事件里有退出码时用它（不再解析文字），展开后先输出、再错误输出（设计 2026-10-23 5.4）", () => {
    const html = renderToStaticMarkup(
      <ToolLine
        toolName="execute"
        args={{ command: "python a.py" }}
        status={done}
        result={"合计 3"}
        isError={false}
        artifact={{ waiting: false, exitCode: 3, stderr: "Traceback: boom" }}
      />,
    );
    expect(html).toContain("退出码 3");
    expect(html).toContain("错误输出");
    expect(html.indexOf("合计 3")).toBeLessThan(html.indexOf("Traceback: boom"));
  });

  it("工具组的出错数算上退出码不是 0 的命令", () => {
    const failed = {
      toolName: "execute",
      args: {},
      status: done,
      result: "x",
      isError: false,
      artifact: { waiting: false, exitCode: 1 },
    };
    expect(failedCount([failed])).toBe(1);
  });
});

describe("工具组的进行中说法（积压小问题 I15）", () => {
  it("有运行中的写“正在<动词>…”（取最后一个运行中的）；都结束了为空", () => {
    const tool = (toolName: string, type: string) => ({ toolName, args: {}, status: { type } });
    expect(
      runningLabel([
        tool("read_file", "complete"),
        tool("execute", "running"),
        tool("ls", "running"),
      ]),
    ).toBe("正在列出目录…");
    expect(runningLabel([tool("read_file", "complete")])).toBeNull();
  });
});
