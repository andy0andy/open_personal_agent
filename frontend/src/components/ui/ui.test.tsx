import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Button } from "./Button";
import { ConfirmDialog } from "./ConfirmDialog";
import { Modal } from "./Modal";
import { Tabs } from "./Tabs";
import { TextField } from "./Field";
import { PageHeader } from "./PageHeader";
import { Panel } from "./Panel";
import { StatusDot } from "./StatusDot";
import { Switch } from "./Switch";
import { Tag } from "./Tag";

describe("共用界面组件", () => {
  it("开关是 switch 角色，带当前状态与名称", () => {
    const html = renderToStaticMarkup(<Switch checked label="启用 excel" onChange={() => {}} />);
    expect(html).toContain('role="switch"');
    expect(html).toContain('aria-checked="true"');
    expect(html).toContain('aria-label="启用 excel"');
  });

  it("开关是圆角胶囊（设计 2026-10-22 2.3）", () => {
    const html = renderToStaticMarkup(<Switch checked={false} label="启用" onChange={() => {}} />);
    expect(html).toContain("rounded-full");
  });

  it("按钮：8 像素圆角、句子写法，不用等宽大写", () => {
    const html = renderToStaticMarkup(<Button variant="primary">新增模型</Button>);
    expect(html).toContain("rounded-lg");
    expect(html).not.toContain("uppercase");
    expect(html).not.toContain("font-mono");
  });

  it("状态点：带名称时读屏读得出来，运行中会呼吸", () => {
    const named = renderToStaticMarkup(<StatusDot tone="info" pulse label="运行中" />);
    expect(named).toContain('role="img"');
    expect(named).toContain('aria-label="运行中"');
    expect(named).toContain("animate-pulse");
    const plain = renderToStaticMarkup(<StatusDot tone="idle" />);
    expect(plain).toContain('aria-hidden="true"');
    expect(plain).not.toContain("animate-pulse");
  });

  it("页头：标题是一级标题，说明在下一行", () => {
    const html = renderToStaticMarkup(<PageHeader title="模型" subtitle="4 个已登记" />);
    expect(html).toMatch(/<h1[^>]*>模型<\/h1><p[^>]*>4 个已登记<\/p>/);
  });

  it("卡片：12 像素圆角，区块标题不用全大写", () => {
    const html = renderToStaticMarkup(
      <Panel title="已登记模型">
        <p>内容</p>
      </Panel>,
    );
    expect(html).toContain("rounded-xl");
    expect(html).not.toContain("uppercase");
  });

  it("标签：实心样式给默认模型用", () => {
    const html = renderToStaticMarkup(<Tag tone="solid">默认</Tag>);
    expect(html).toContain("bg-primary");
    expect(html).toContain("text-primary-foreground");
  });
});

describe("表单项的读屏提示（积压小问题 H2）", () => {
  it("出错时 aria-invalid 并指向错误文字；正常时指向提示", () => {
    const wrong = renderToStaticMarkup(
      <TextField label="名称" value="" onChange={() => {}} error="名称不能为空" />,
    );
    const input = /<input[^>]*>/.exec(wrong)?.[0] ?? "";
    expect(input).toContain('aria-invalid="true"');
    const describedBy = /aria-describedby="([^"]+)"/.exec(input)?.[1];
    expect(wrong).toContain(`id="${describedBy}"`);
    const hinted = renderToStaticMarkup(
      <TextField label="名称" value="" onChange={() => {}} hint="小写字母开头" />,
    );
    expect(hinted).toMatch(/aria-describedby="[^"]+"/);
    expect(hinted).not.toContain("aria-invalid");
  });

  it("多行输入框也带上其余属性", () => {
    const html = renderToStaticMarkup(
      <TextField label="说明" value="" onChange={() => {}} multiline name="description" required />,
    );
    expect(html).toMatch(/<textarea[^>]*name="description"/);
    expect(html).toMatch(/<textarea[^>]*required/);
  });
});

describe("对话框与标签页跟上新的样式（积压小问题 H5）", () => {
  it("对话框、确认框 12 像素圆角；标签页不用等宽大写", () => {
    const modal = renderToStaticMarkup(
      <Modal title="上传技能" open onClose={() => {}}>
        内容
      </Modal>,
    );
    const confirm = renderToStaticMarkup(
      <ConfirmDialog
        title="删除？"
        open
        confirmLabel="删除"
        onConfirm={() => {}}
        onCancel={() => {}}
      >
        说明
      </ConfirmDialog>,
    );
    expect(modal).toMatch(/role="dialog"[^>]*class="[^"]*rounded-xl/);
    expect(confirm).toMatch(/role="alertdialog"[^>]*class="[^"]*rounded-xl/);
    const tabs = renderToStaticMarkup(
      <Tabs tabs={[{ id: "a", label: "正文" }]} value="a" onChange={() => {}} />,
    );
    expect(tabs).not.toMatch(/font-mono|uppercase|tracking-wider/);
  });
});
