import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import { dataFilesQuery, skillsQuery } from "../../api/queries";
import { Button } from "../../components/ui/Button";
import { PageHeader } from "../../components/ui/PageHeader";
import { Panel } from "../../components/ui/Panel";
import { Switch } from "../../components/ui/Switch";
import { SkillDrawer } from "./SkillDrawer";
import {
  type SkillFilter,
  filterSkills,
  lastUsedLabel,
  skillsStateError,
  uploadedNotice,
  visibleNotice,
} from "./skills";
import { UploadSkillDialog } from "./UploadSkillDialog";

const FILTERS: [SkillFilter, string][] = [
  ["all", "全部"],
  ["enabled", "已启用"],
  ["disabled", "已停用"],
];

const errorText = (exc: unknown) => (exc instanceof Error ? exc.message : String(exc));

/**
 * 技能页（设计文档 6，原型 04）。全部技能都在 .workdata/skills/（首次启动写入的 excel 与上传的），
 * 都能停用、删除；停用清单在 .workdata/config/skills.yaml（D22）。
 */
export function SkillsPage() {
  const queryClient = useQueryClient();
  const listed = useQuery(skillsQuery);
  const skills = listed.data ?? [];
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ id: string; text: string } | null>(null);
  const dataFiles = useQuery(dataFilesQuery);
  const stateError = skillsStateError(dataFiles.data ?? []);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["settings", "skills"] });
  const act = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
    } catch (exc) {
      setError(errorText(exc));
    }
    await refresh();
  };
  const [filter, setFilter] = useState<SkillFilter>("all");
  const [query, setQuery] = useState("");
  const [viewing, setViewing] = useState<string | null>(null);
  const [uploadKey, setUploadKey] = useState<number | null>(null);
  const enabled = skills.filter((skill) => skill.enabled).length;
  const shown = filterSkills(skills, filter, query);
  const opened = skills.find((skill) => skill.id === viewing);
  const now = new Date();

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title="技能"
        subtitle={`已启用 ${enabled} / 共 ${skills.length}`}
        actions={
          <>
            <input
              aria-label="搜索技能"
              placeholder="搜索技能"
              className="h-8 w-48 rounded-lg border border-input bg-background px-2.5 text-[13px] placeholder:text-muted-foreground"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <Button variant="primary" onClick={() => setUploadKey((key) => (key ?? 0) + 1)}>
              <Upload className="size-4" aria-hidden="true" />
              上传技能
            </Button>
          </>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-[55rem] gap-6 p-6">
          <nav aria-label="筛选技能" className="flex w-36 shrink-0 flex-col gap-0.5">
            {FILTERS.map(([value, label]) => (
              <button
                key={value}
                aria-pressed={filter === value}
                onClick={() => setFilter(value)}
                className={`flex h-[34px] items-center justify-between rounded-lg px-2.5 text-sm transition-colors ${
                  filter === value
                    ? "bg-accent font-medium text-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                {label}
                <span className="font-mono text-xs">{filterSkills(skills, value, "").length}</span>
              </button>
            ))}
          </nav>
          <div className="min-w-0 flex-1">
            {error && !opened && <p className="mb-3 text-sm text-danger">{error}</p>}
            {stateError && (
              <p className="mb-3 text-sm text-danger">
                停用清单读不出来，暂时所有技能都按启用处理：{stateError}
              </p>
            )}
            {visibleNotice(notice, skills) && (
              <p className="mb-3 text-sm text-warning">{visibleNotice(notice, skills)}</p>
            )}
            {listed.isError && (
              <p className="mb-3 text-sm text-danger">读不出技能：{errorText(listed.error)}</p>
            )}
            <Panel title="技能">
              {shown.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {listed.isLoading ? "加载中…" : "没有符合的技能"}
                </p>
              ) : (
                <ul className="divide-y divide-border">
                  {shown.map((skill) => (
                    <li
                      key={skill.id}
                      className={`flex items-center gap-3 py-3 ${skill.enabled ? "" : "opacity-50"}`}
                    >
                      <Switch
                        checked={skill.enabled}
                        label={`启用 ${skill.name}`}
                        onChange={(next) => void act(() => api.setSkillEnabled(skill.id, next))}
                      />
                      <div className="min-w-0 flex-1">
                        <span className="font-mono text-sm">{skill.name}</span>
                        {/* 说明最多两行（设计 2026-10-22 第 4 节），全文在悬停提示与"查看"里 */}
                        <p
                          className="line-clamp-2 text-xs text-muted-foreground"
                          title={skill.description}
                        >
                          {skill.description}
                        </p>
                        {skill.notice && <p className="text-xs text-warning">{skill.notice}</p>}
                        <p className="text-xs text-muted-foreground">
                          {lastUsedLabel(skill.last_used_at, now)}
                        </p>
                      </div>
                      <Button onClick={() => setViewing(skill.id)}>查看</Button>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
        </div>
      </div>
      {opened && (
        <SkillDrawer
          skill={opened}
          error={error}
          onClose={() => setViewing(null)}
          onToggle={(next) => void act(() => api.setSkillEnabled(opened.id, next))}
          onDelete={() =>
            void act(async () => {
              await api.deleteSkill(opened.id);
              setViewing(null);
            })
          }
        />
      )}
      {uploadKey !== null && (
        <UploadSkillDialog
          key={uploadKey}
          existingNames={skills.flatMap((skill) => [skill.id, skill.name])}
          onClose={() => setUploadKey(null)}
          onInstalled={async (skill) => {
            await refresh();
            const text = uploadedNotice(skill);
            setNotice(text ? { id: skill.id, text } : null);
            setUploadKey(null);
          }}
        />
      )}
    </div>
  );
}
