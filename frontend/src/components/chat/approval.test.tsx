import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ApprovalItem } from "../../features/chat/reducer";
import { ApprovalPart } from "./approval";

const card = (status: ApprovalItem["status"], extra: Partial<ApprovalItem> = {}) =>
  renderToStaticMarkup(
    <ApprovalPart
      type="data"
      name="approval"
      status={{ type: "complete" }}
      data={
        {
          kind: "approval",
          id: "approval-r1-3",
          runId: "r1",
          seq: 3,
          status,
          requests: [
            {
              interrupt_id: "i1",
              agent_path: ["main"],
              actions: [
                {
                  call_id: "c1",
                  name: "execute",
                  args: { command: "python a.py" },
                  server: null,
                  description: "",
                  allowed: ["approve", "edit", "reject"],
                },
              ],
            },
          ],
          ...extra,
        } satisfies ApprovalItem
      }
    />,
  );

describe("审批卡片", () => {
  const html = card("pending");

  it("标题、命令和执行环境的说明", () => {
    expect(html).toContain("要执行这条命令吗？");
    expect(html).toContain("python a.py");
    // 去掉沙箱后（D20、D23）命令不只碰得到会话里的文件：说清楚，看清再同意
    expect(html).toContain(
      "在本会话的目录里运行，能上网，也能读到项目里的大部分文件、连到本项目的数据库",
    );
    expect(html).not.toContain('"command"');
  });

  it("按钮从左到右：拒绝、回复一句话、修改后执行、同意", () => {
    const positions = ["拒绝", "回复一句话", "修改后执行", "同意"].map((label) =>
      html.search(new RegExp(`<button[^>]*>${label}`)),
    );
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
  });

  it("主按钮是“同意”，按键提示不计入按钮名称", () => {
    expect(html).toMatch(/<button[^>]*bg-primary[^>]*>同意/);
    expect(html).toMatch(/<kbd aria-hidden="true"[^>]*>↵<\/kbd>/);
    expect(html).toMatch(/<kbd aria-hidden="true"[^>]*>Esc<\/kbd>/);
  });

  it("子智能体审批的长回复可以截断，完整内容在悬停提示里", () => {
    const reply = "y".repeat(300);
    const done = card("resolved", {
      answers: [{ interrupt_id: "i1", decisions: [{ type: "reject", message: reply }] }],
    });
    expect(done).toMatch(/<span title="已回复：y{300}" class="[^"]*min-w-0[^"]*truncate[^"]*">/);
  });

  it("处理完以后（工具不在这一层时才会显示）只剩一行结果，没有按钮", () => {
    const done = card("resolved", {
      answers: [{ interrupt_id: "i1", decisions: [{ type: "approve" }] }],
    });
    expect(done).toContain("已同意");
    expect(done).not.toContain("<button");
  });
});
