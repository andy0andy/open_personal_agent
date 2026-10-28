import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PermissionMenu, PermissionSelect } from "./PermissionSelect";

describe("权限选择", () => {
  it("按钮显示当前档位；运行中改过时提示从下一条消息开始生效", () => {
    const html = renderToStaticMarkup(
      <PermissionSelect value="ask_execute" onChange={() => {}} pendingHint />,
    );
    expect(html).toContain("只问执行命令");
    expect(html).toContain('aria-haspopup="menu"');
    expect(html).toContain("从下一条消息开始生效");
    const quiet = renderToStaticMarkup(
      <PermissionSelect value="ask" onChange={() => {}} pendingHint={false} />,
    );
    expect(quiet).not.toContain("从下一条消息开始生效");
  });

  it("列表有三项，当前项打勾", () => {
    const html = renderToStaticMarkup(<PermissionMenu value="skip" onChoose={() => {}} />);
    expect(html.match(/role="menuitemradio"/g)).toHaveLength(3);
    expect(html.match(/aria-checked="true"/g)).toHaveLength(1);
    const checked = html.indexOf('aria-checked="true"');
    expect(html.indexOf("跳过所有审批", checked)).toBeGreaterThan(checked);
    expect(html).toContain("什么都不问（危险命令除外），直接执行，包括命令");
  });
});
