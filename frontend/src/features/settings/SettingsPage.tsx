import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Lock } from "lucide-react";
import { useState } from "react";
import { api, readableError } from "../../api/client";
import { appSettingsQuery, dataFilesQuery, modelsQuery } from "../../api/queries";
import type { DataFileView, SettingView } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { PageHeader } from "../../components/ui/PageHeader";
import { Panel } from "../../components/ui/Panel";
import { StatusDot } from "../../components/ui/StatusDot";
import { Switch } from "../../components/ui/Switch";
import { Tag } from "../../components/ui/Tag";
import { useCopy } from "../../components/useCopy";
import {
  groupSettings,
  parseInput,
  pendingRestartCount,
  rowBadge,
  sectionPending,
} from "./settings";

const FILES_ID = "settings-files";
const sectionId = (id: string) => `settings-${id}`;

/** 跳到页内的某一节（系统开了"减少动效"时直接跳）。 */
function scrollToSection(id: string): void {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.getElementById(id)?.scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
}

/**
 * 设置页（D22，设计 2026-10-22 第 4 节）：设置存在数据库里，同名环境变量（.env）优先。
 * 左边分节导航（带项数，有待重启的节带琥珀点）；页顶提示有几项等重启；生效时机每节说一次；
 * .env 指定的项写明变量名；只读项写原因。下面列出 .workdata 里各文件的位置与状态。
 * 模型、技能、MCP 在各自的页面上管；明暗切换在侧栏。
 */
export function SettingsPage() {
  const settings = useQuery(appSettingsQuery);
  const files = useQuery(dataFilesQuery);
  const views = settings.data ?? [];
  const sections = groupSettings(views);
  const pending = pendingRestartCount(views);
  const firstPending = sections.find((section) => sectionPending(section.items));
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="设置" subtitle="改过的存在数据库里；.env 里写了同名变量的项以 .env 为准" />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[55rem] space-y-5 p-6">
          {pending > 0 && (
            <RestartBanner
              count={pending}
              onShow={firstPending ? () => scrollToSection(sectionId(firstPending.id)) : undefined}
            />
          )}
          {settings.isError && (
            <p className="text-sm text-danger">读不出设置：{readableError(settings.error)}</p>
          )}
          <div className="flex items-start gap-6">
            <nav
              aria-label="设置分节"
              className="sticky top-0 hidden w-44 shrink-0 flex-col gap-0.5 md:flex"
            >
              {sections.map((section) => (
                <SectionLink
                  key={section.id}
                  title={section.title}
                  count={section.items.length}
                  pending={sectionPending(section.items)}
                  onClick={() => scrollToSection(sectionId(section.id))}
                />
              ))}
              <SectionLink
                title=".workdata 文件"
                count={files.data?.length ?? 0}
                pending={false}
                onClick={() => scrollToSection(FILES_ID)}
              />
            </nav>
            <div className="min-w-0 flex-1 space-y-5">
              {sections.map((section) => {
                const mixed = new Set(section.items.map((view) => view.apply)).size > 1;
                return (
                  <Panel
                    key={section.id}
                    id={sectionId(section.id)}
                    title={section.title}
                    note={section.note}
                  >
                    <ul className="divide-y divide-border">
                      {section.items.map((view) => (
                        <SettingRow key={view.key} view={view} showApply={mixed} />
                      ))}
                    </ul>
                  </Panel>
                );
              })}
              <Panel
                id={FILES_ID}
                title=".workdata 文件"
                note="MCP 服务清单、审批规则、技能都在这里，也可以手改"
              >
                {files.isError ? (
                  <p className="text-sm text-danger">
                    读不出文件状态：{readableError(files.error)}
                  </p>
                ) : (
                  <ul className="divide-y divide-border">
                    {(files.data ?? []).map((file) => (
                      <FileRow key={file.path} file={file} />
                    ))}
                  </ul>
                )}
              </Panel>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function SectionLink({
  title,
  count,
  pending,
  onClick,
}: {
  title: string;
  count: number;
  pending: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex h-[34px] items-center gap-2 rounded-lg px-2.5 text-left text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      <span className="min-w-0 flex-1 truncate">{title}</span>
      {pending && <StatusDot tone="warning" label="有待重启的项" />}
      <span className="font-mono text-xs">{count}</span>
    </button>
  );
}

/** 页顶提示：几项已保存、要重启才生效；命令可以一键复制。 */
function RestartBanner({ count, onShow }: { count: number; onShow?: () => void }) {
  const { state, copy } = useCopy();
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-warning bg-warning-soft px-4 py-3 text-sm">
      <StatusDot tone="warning" />
      <span className="font-medium">{`${count} 项已保存，重启后生效`}</span>
      <span className="text-muted-foreground">在终端执行</span>
      <code className="rounded-md border border-border bg-background px-2 py-0.5 font-mono text-[13px]">
        make restart
      </code>
      <button
        type="button"
        aria-label="复制命令"
        title="复制命令"
        onClick={() => copy("make restart")}
        className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        {state === "copied" ? (
          <Check aria-hidden="true" className="size-3.5" />
        ) : (
          <Copy aria-hidden="true" className="size-3.5" />
        )}
      </button>
      {onShow && (
        <button
          type="button"
          onClick={onShow}
          className="ml-auto text-[13px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          {`看看是哪 ${count} 项`}
        </button>
      )}
    </div>
  );
}

function SettingRow({ view, showApply }: { view: SettingView; showApply: boolean }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  // 默认对话模型也显示在模型页：设置相关的数据一起刷新
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["settings"] });
  const save = useMutation({
    mutationFn: (value: unknown) => api.updateAppSetting(view.key, value),
    onSuccess: async () => {
      setError(null);
      await refresh();
    },
    onError: (exc) => setError(readableError(exc)),
  });
  const reset = useMutation({
    mutationFn: () => api.resetAppSetting(view.key),
    onSuccess: async () => {
      setError(null);
      await refresh();
    },
    onError: (exc) => setError(readableError(exc)),
  });
  const badge = rowBadge(view);
  const readonly = !view.editable && view.source !== "env";
  return (
    <li className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 py-3 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1 space-y-1">
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <span>{view.label}</span>
          {badge && (
            <Tag tone={badge.tone}>
              {badge.tone === "warning" && <StatusDot tone="warning" />}
              {badge.text}
            </Tag>
          )}
          {showApply && view.apply === "now" && <Tag tone="outline">立即生效</Tag>}
        </p>
        <p className="font-mono text-xs text-muted-foreground">{view.key}</p>
        {view.source === "env" && (
          <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <Lock aria-hidden="true" className="size-3.5 shrink-0" />由 .env 的
            <span className="font-mono text-foreground">{view.env_name}</span>
            指定，要改请改 .env
          </p>
        )}
        {view.note ? (
          <p className="text-xs text-muted-foreground">{view.note}</p>
        ) : (
          readonly && <p className="text-xs text-muted-foreground">页面上不能改</p>
        )}
        {view.restart_pending && (
          <p className="text-xs text-muted-foreground">
            {`已保存，重启后生效；运行中的是 ${formatValue(view.value)}`}
          </p>
        )}
        {error && <p className="text-xs text-danger">{error}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {view.source === "db" && view.editable && (
          <Button variant="ghost" disabled={reset.isPending} onClick={() => reset.mutate()}>
            恢复默认
          </Button>
        )}
        <SettingControl
          view={view}
          busy={save.isPending || reset.isPending}
          onSave={(value) => save.mutate(value)}
          onInvalid={setError}
        />
      </div>
    </li>
  );
}

const BOX = "h-8 rounded-lg border border-input bg-background px-2.5 font-mono text-xs";

function SettingControl({
  view,
  busy,
  onSave,
  onInvalid,
}: {
  view: SettingView;
  busy: boolean;
  onSave: (value: unknown) => void;
  onInvalid: (error: string) => void;
}) {
  const models = useQuery(modelsQuery);
  if (!view.editable) {
    return (
      <span
        className="flex h-8 max-w-80 items-center truncate rounded-lg border border-border bg-muted px-2.5 font-mono text-xs"
        title={formatValue(view.upcoming)}
      >
        {formatValue(view.upcoming)}
      </span>
    );
  }
  if (view.key === "agent.default_model") {
    const chatModels = (models.data ?? []).filter((model) => model.mode === "chat");
    const current = String(view.upcoming);
    return (
      <select
        aria-label={view.label}
        disabled={busy}
        className={BOX}
        value={current}
        onChange={(event) => onSave(event.target.value)}
      >
        {!chatModels.some((model) => model.name === current) && (
          <option value={current}>{current}</option>
        )}
        {chatModels.map((model) => (
          <option key={model.name} value={model.name}>
            {model.name}
          </option>
        ))}
      </select>
    );
  }
  if (typeof view.upcoming === "boolean") {
    const checked = view.upcoming;
    return <Switch checked={checked} label={view.label} onChange={(next) => onSave(next)} />;
  }
  // 换了存的值（保存、恢复默认）就按新值重新显示输入框
  return (
    <TextSetting
      key={JSON.stringify(view.upcoming)}
      view={view}
      busy={busy}
      onSave={onSave}
      onInvalid={onInvalid}
    />
  );
}

function TextSetting({
  view,
  busy,
  onSave,
  onInvalid,
}: {
  view: SettingView;
  busy: boolean;
  onSave: (value: unknown) => void;
  onInvalid: (error: string) => void;
}) {
  const [text, setText] = useState(String(view.upcoming ?? ""));
  const commit = () => {
    const parsed = parseInput(view, text);
    if (!parsed.ok) {
      onInvalid(parsed.error);
      return;
    }
    if (parsed.value !== view.upcoming) onSave(parsed.value);
  };
  return (
    <input
      aria-label={view.label}
      type={typeof view.value === "number" ? "number" : "text"}
      step="any"
      disabled={busy}
      value={text}
      onChange={(event) => setText(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
      }}
      className={`${BOX} w-40 text-right`}
    />
  );
}

function FileRow({ file }: { file: DataFileView }) {
  const tone = file.state === "ok" ? "success" : file.state === "error" ? "danger" : "default";
  const label = file.state === "ok" ? "正常" : file.state === "error" ? "有误" : "还没有";
  return (
    <li className="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1">
        <p className="text-sm">{file.purpose}</p>
        <p className="truncate font-mono text-xs text-muted-foreground">{file.path}</p>
        {file.detail && <p className="text-xs text-danger">{file.detail}</p>}
      </div>
      <Tag tone={tone}>{label}</Tag>
    </li>
  );
}

/** 只读项的显示：模型来源这类列表显示各自的名字。 */
function formatValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value
      .map((item) =>
        item && typeof item === "object" && "label" in item ? String(item.label) : String(item),
      )
      .join("、");
  }
  if (typeof value === "boolean") return value ? "开" : "关";
  return String(value ?? "");
}
