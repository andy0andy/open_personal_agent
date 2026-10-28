import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DeleteThreadDialog } from "./DeleteThreadDialog";

describe("删除会话的确认框（积压小问题 C3）", () => {
  it("说明它记下的记忆与加入知识库的文档会保留", () => {
    const html = renderToStaticMarkup(
      <DeleteThreadDialog
        title="周报"
        pending={false}
        error={null}
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(html).toContain("它记下的记忆、加入知识库的文档会保留，可在知识库页管理。");
  });
});
