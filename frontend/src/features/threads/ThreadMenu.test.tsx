import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { exportUrl } from "../../api/client";
import { ThreadMenu } from "./ThreadMenu";

const position = { threadId: "t1", x: 0, y: 0, trigger: null };
const noop = () => undefined;

describe("会话菜单", () => {
  it("顶栏的菜单多一项“导出 Markdown”（设计 2026-10-23 6.2）；会话列表的没有", () => {
    const header = renderToStaticMarkup(
      <ThreadMenu
        position={position}
        onRename={noop}
        onDelete={noop}
        onClose={noop}
        onExport={noop}
      />,
    );
    expect(header).toContain("导出 Markdown");
    const list = renderToStaticMarkup(
      <ThreadMenu position={position} onRename={noop} onDelete={noop} onClose={noop} />,
    );
    expect(list).not.toContain("导出 Markdown");
  });

  it("归档；已归档的显示“取消归档”（设计 2026-10-23 6.5）", () => {
    const active = renderToStaticMarkup(
      <ThreadMenu
        position={position}
        onRename={noop}
        onDelete={noop}
        onClose={noop}
        onArchive={noop}
      />,
    );
    expect(active).toContain("归档");
    expect(active).not.toContain("取消归档");
    const archived = renderToStaticMarkup(
      <ThreadMenu
        position={position}
        onRename={noop}
        onDelete={noop}
        onClose={noop}
        onArchive={noop}
        archived
      />,
    );
    expect(archived).toContain("取消归档");
  });

  it("导出地址", () => {
    // 每轮的时间按浏览器所在时区写（8000 实测：原来按 UTC）
    expect(exportUrl("t1", "Asia/Shanghai")).toBe("/api/threads/t1/export?tz=Asia%2FShanghai");
  });
});
