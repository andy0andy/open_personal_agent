import { describe, expect, it } from "vitest";
import type { SkillInfo } from "../../api/types";
import {
  filterSkills,
  inspectUpload,
  lastUsedLabel,
  parseSkillMd,
  skillsStateError,
  uploadedNotice,
  visibleNotice,
} from "./skills";

const skill = (id: string, description: string, enabled: boolean): SkillInfo => ({
  id,
  name: id,
  description,
  error: null,
  enabled,
  location: `.workdata/skills/${id}/`,
  added_at: null,
});

const SKILLS = [
  skill("excel", "读取、清洗、汇总 Excel 表格", true),
  skill("周报写作", "按模板写周报", true),
  skill("旅行规划", "安排行程与预算", false),
];

const SKILL_MD = "---\nname: 会议纪要\ndescription: 整理会议记录\n---\n\n# 怎么整理\n";

describe("读 SKILL.md 开头的名称与说明", () => {
  it("开头 --- 之间写 name 与 description", () => {
    expect(parseSkillMd("---\nname: excel\ndescription: 处理表格\n---\n正文")).toEqual({
      name: "excel",
      description: "处理表格",
    });
  });

  it("记事本存的文件：开头带 BOM、换行是 \\r\\n", () => {
    expect(
      parseSkillMd("\uFEFF---\r\nname: excel\r\ndescription: 处理表格\r\n---\r\n正文"),
    ).toEqual({
      name: "excel",
      description: "处理表格",
    });
  });

  it("缺开头或缺字段时给出原因", () => {
    expect(parseSkillMd("# 没有开头")).toEqual({
      error: "SKILL.md 开头要有 --- 包起来的 name 与 description",
    });
    expect(parseSkillMd("---\nname: excel\n---\n")).toEqual({
      error: "SKILL.md 开头缺少 description",
    });
  });
});

describe("识别上传的技能", () => {
  it("单个 SKILL.md", () => {
    expect(inspectUpload([{ path: "SKILL.md", text: SKILL_MD }], [])).toEqual({
      kind: "ok",
      name: "会议纪要",
      description: "整理会议记录",
      fileCount: 1,
    });
  });

  it("技能文件夹：数上所有文件；与已有技能同名（不分大小写）时不能安装", () => {
    const folder = [
      { path: "会议纪要/SKILL.md", text: SKILL_MD },
      { path: "会议纪要/模板.md" },
      { path: "会议纪要/scripts/整理.py" },
    ];
    expect(inspectUpload(folder, [])).toMatchObject({ kind: "ok", fileCount: 3 });
    expect(inspectUpload(folder, ["会议纪要"])).toEqual({
      kind: "error",
      message: "已有同名技能「会议纪要」，换个名字再上传",
    });
    const excel = [{ path: "SKILL.md", text: "---\nname: Excel\ndescription: x\n---\n" }];
    expect(inspectUpload(excel, ["excel"])).toMatchObject({ kind: "error" });
  });

  it("文件夹里没有 SKILL.md、或不是技能文件时不能安装", () => {
    expect(inspectUpload([{ path: "会议纪要/模板.md" }], [])).toEqual({
      kind: "error",
      message: "文件夹里没有 SKILL.md",
    });
    expect(inspectUpload([{ path: "报告.pdf" }], [])).toEqual({
      kind: "error",
      message: "只能上传技能文件夹、.zip 或 SKILL.md",
    });
  });

  it("压缩包在预览里不解析", () => {
    expect(inspectUpload([{ path: "x.zip" }], [])).toEqual({ kind: "zip", fileName: "x.zip" });
  });
});

describe("筛选与搜索", () => {
  it("按启用状态筛选；搜索同时匹配名称与说明，不分大小写", () => {
    expect(filterSkills(SKILLS, "enabled", "").map((skill) => skill.name)).toEqual([
      "excel",
      "周报写作",
    ]);
    expect(filterSkills(SKILLS, "disabled", "").map((skill) => skill.name)).toEqual(["旅行规划"]);
    expect(filterSkills(SKILLS, "all", "EXCEL").map((skill) => skill.name)).toEqual(["excel"]);
    expect(filterSkills(SKILLS, "all", "行程").map((skill) => skill.name)).toEqual(["旅行规划"]);
  });
});

describe("最近使用时间与说明长度提示（设计 2026-10-23 7.7）", () => {
  const now = new Date(2026, 9, 24, 15, 0);

  it("没用过写“从未使用”；用过的写最近一次的时间", () => {
    expect(lastUsedLabel(null, now)).toBe("从未使用");
    expect(lastUsedLabel(undefined, now)).toBe("从未使用");
    expect(lastUsedLabel(new Date(2026, 9, 24, 9, 5).toISOString(), now)).toBe("最近使用：09:05");
    expect(lastUsedLabel(new Date(2026, 9, 23, 20, 0).toISOString(), now)).toBe("最近使用：昨天");
    expect(lastUsedLabel(new Date(2026, 9, 2, 8, 0).toISOString(), now)).toBe("最近使用：10月2日");
  });

  it("上传后说明太长时提示（提示原文以后端为准），不长时不提示", () => {
    const long = { ...skill("周报写作", "…", true), notice: "说明有 400 字，说明尽量短：…" };
    expect(uploadedNotice(long)).toBe("已上传「周报写作」。说明有 400 字，说明尽量短：…");
    expect(uploadedNotice(skill("excel", "处理表格", true))).toBeNull();
  });
});

describe("技能页的提示（积压小问题 F1、F10）", () => {
  it("删掉那个技能后上传提示不再显示", () => {
    const notice = { id: "周报写作", text: "已上传「周报写作」。说明有 400 字…" };
    expect(visibleNotice(notice, SKILLS)).toBe(notice.text);
    expect(
      visibleNotice(
        notice,
        SKILLS.filter((s) => s.id !== "周报写作"),
      ),
    ).toBeNull();
    expect(visibleNotice(null, SKILLS)).toBeNull();
  });

  it("停用清单写坏时给出原因；正常或文件不存在时为空", () => {
    const file = (state: string, detail: string | null = null) => ({
      path: ".workdata/config/skills.yaml",
      purpose: "停用的技能",
      state,
      detail,
    });
    expect(skillsStateError([file("error", "skills.yaml 有误：第 2 行不是合法的 YAML")])).toBe(
      "skills.yaml 有误：第 2 行不是合法的 YAML",
    );
    expect(skillsStateError([file("ok")])).toBeNull();
    expect(skillsStateError([file("missing")])).toBeNull();
  });
});

describe("上传前先查文件数与大小（积压小问题 F6）", () => {
  const md = "---\nname: 周报\ndescription: 写周报\n---\n";
  const limits = { maxFiles: 500, maxBytes: 50 * 1024 * 1024 };

  it("文件超过 500 个时不让上传", () => {
    const files = [
      { path: "周报/SKILL.md", text: md, size: 10 },
      ...Array.from({ length: 500 }, (_, i) => ({ path: `周报/ref/${i}.md`, size: 1 })),
    ];
    expect(inspectUpload(files, [], limits)).toEqual({
      kind: "error",
      message: "文件太多：一个技能最多 500 个文件",
    });
  });

  it("Mac 夹带的 .DS_Store、__MACOSX/ 不算数（与后端一致，审查 Minor 5）", () => {
    const files = [
      { path: "周报/SKILL.md", text: md, size: 10 },
      ...Array.from({ length: 499 }, (_, i) => ({ path: `周报/ref/${i}.md`, size: 1 })),
      { path: "周报/.DS_Store", size: 6148 },
      { path: "周报/ref/.DS_Store", size: 6148 },
      { path: "__MACOSX/周报/._SKILL.md", size: 4096 },
    ];
    expect(inspectUpload(files, [], limits)).toMatchObject({ kind: "ok", fileCount: 500 });
  });

  it("合计超过上传上限时不让上传", () => {
    const files = [
      { path: "周报/SKILL.md", text: md, size: 10 },
      { path: "周报/data.bin", size: 50 * 1024 * 1024 },
    ];
    expect(inspectUpload(files, [], limits)).toEqual({
      kind: "error",
      message: "文件太大：合计超过上传上限 50MB",
    });
  });
});
