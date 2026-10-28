import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { skillDetailQuery } from "../../api/queries";
import type { SkillInfo } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { Drawer } from "../../components/ui/Drawer";
import { Switch } from "../../components/ui/Switch";
import { Tabs } from "../../components/ui/Tabs";
import { lastUsedLabel } from "./skills";

/**
 * 查看技能的右侧抽屉（只读，设计文档 6）：开关、基本信息、SKILL.md 正文与文件列表、删除。
 * 任何技能都能停用、删除（D22）。
 */
export function SkillDrawer({
  skill,
  error,
  onToggle,
  onDelete,
  onClose,
}: {
  skill: SkillInfo;
  error: string | null;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState("body");
  const [confirming, setConfirming] = useState(false);
  const detail = useQuery(skillDetailQuery(skill.id));
  return (
    <>
      <Drawer
        title={skill.name}
        open
        onClose={onClose}
        footer={
          <Button variant="danger" onClick={() => setConfirming(true)}>
            删除技能
          </Button>
        }
      >
        <div className="flex items-center gap-2 text-sm">
          <Switch checked={skill.enabled} label={`启用 ${skill.name}`} onChange={onToggle} />
          {skill.enabled ? "已启用" : "已停用：智能体暂时看不到它，文件保留"}
        </div>
        {error && <p className="text-xs text-danger">{error}</p>}
        {skill.error && <p className="text-xs text-danger">{skill.error}</p>}
        {skill.notice && <p className="text-xs text-warning">{skill.notice}</p>}
        <dl className="grid grid-cols-[5rem_1fr] gap-x-3 gap-y-2 text-sm">
          <dt className="text-muted-foreground">描述</dt>
          <dd>{skill.description}</dd>
          <dt className="text-muted-foreground">存放位置</dt>
          <dd className="font-mono text-xs">{skill.location}</dd>
          <dt className="text-muted-foreground">添加时间</dt>
          <dd className="font-mono text-xs">{skill.added_at ?? "—"}</dd>
          <dt className="text-muted-foreground">使用情况</dt>
          <dd className="text-xs">{lastUsedLabel(skill.last_used_at, new Date())}</dd>
        </dl>
        <Tabs
          tabs={[
            { id: "body", label: "SKILL.md" },
            { id: "files", label: "文件" },
          ]}
          value={tab}
          onChange={setTab}
        />
        {detail.isError ? (
          <p className="text-sm text-danger">读不出这个技能：{String(detail.error.message)}</p>
        ) : !detail.data ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : tab === "body" ? (
          <div className="markdown text-sm">
            <Markdown remarkPlugins={[remarkGfm]}>{detail.data.body}</Markdown>
          </div>
        ) : (
          <ul className="space-y-1 font-mono text-xs">
            {detail.data.files.map((file) => (
              <li key={file}>{file}</li>
            ))}
          </ul>
        )}
      </Drawer>
      <ConfirmDialog
        open={confirming}
        title={`删除技能 ${skill.name}？`}
        confirmLabel="删除"
        danger
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false);
          onDelete();
        }}
      >
        <p>删除后智能体就用不到它了，文件夹一并删除。</p>
      </ConfirmDialog>
    </>
  );
}
