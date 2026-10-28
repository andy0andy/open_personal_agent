import { useQuery } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { useState } from "react";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";
import { type DroppedFile, type EntryLike, readDroppedEntries } from "./dropped";
import { api } from "../../api/client";
import { appSettingsQuery } from "../../api/queries";
import type { SkillInfo } from "../../api/types";
import { uploadLimitMb } from "../settings/settings";
import { type UploadFile, type UploadResult, inspectUpload } from "./skills";

// React 的类型里没有选择文件夹用的 webkitdirectory，按普通属性传
const FOLDER_PICKER = { webkitdirectory: "", directory: "" } as Record<string, string>;

/** 读出 SKILL.md 的文字用来在本地先识别；其余文件只记路径，安装时才读内容。 */
async function toUploadFiles(files: DroppedFile[]): Promise<UploadFile[]> {
  return Promise.all(
    files.map(async ({ path, file }) =>
      file.name === "SKILL.md"
        ? { path, text: await file.text(), size: file.size }
        : { path, size: file.size },
    ),
  );
}

/** 文件内容 → base64（读成 data: 地址再去掉前缀，不必自己拼大数组） */
function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(reader.error ?? new Error("读不出文件"));
    reader.readAsDataURL(file);
  });
}

/** 选择文件或文件夹时，浏览器在 webkitRelativePath 里给出带文件夹层级的路径 */
const withPaths = (files: FileList | null): DroppedFile[] =>
  [...(files ?? [])].map((file) => ({ path: file.webkitRelativePath || file.name, file }));

/**
 * 上传技能的对话框（设计文档 6）：拖入或选择技能文件夹 / .zip / 单个 SKILL.md，先在本地识别出名称、
 * 描述、文件数，再点"安装"。压缩包在本地不解析，安装时由后端检查。不许与已有技能同名（D21）。
 */
export function UploadSkillDialog({
  existingNames,
  onInstalled,
  onClose,
}: {
  existingNames: string[];
  onInstalled: (skill: SkillInfo) => Promise<void>;
  onClose: () => void;
}) {
  const settings = useQuery(appSettingsQuery);
  const limitMb = uploadLimitMb(settings.data);
  // 与后端一致：单个技能最多 500 个文件，合计不超过上传上限（还没取到上限时只查文件数）
  const limits = { maxFiles: 500, maxBytes: (limitMb ?? Infinity) * 1024 * 1024 };
  const [result, setResult] = useState<UploadResult | null>(null);
  const [picked, setPicked] = useState<DroppedFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const accept = async (files: DroppedFile[]) => {
    if (files.length === 0) return;
    setFailure(null);
    setResult(inspectUpload(await toUploadFiles(files), existingNames, limits));
    setPicked(files);
  };

  const install = async () => {
    if (result?.kind !== "ok" && result?.kind !== "zip") return;
    setBusy(true);
    setFailure(null);
    try {
      const files = await Promise.all(
        picked.map(async ({ path, file }) => ({ path, content: await toBase64(file) })),
      );
      await onInstalled(await api.uploadSkill(files));
    } catch (exc) {
      setFailure(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="上传技能"
      open
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>取消</Button>
          <Button
            variant="primary"
            disabled={busy || (result?.kind !== "ok" && result?.kind !== "zip")}
            onClick={() => void install()}
          >
            安装
          </Button>
        </>
      }
    >
      <div
        className="flex flex-col items-center gap-3 border border-dashed border-border px-4 py-8 text-sm text-muted-foreground"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          // 条目要在事件处理里当场取出，之后 dataTransfer 就清空了
          const entries = [...event.dataTransfer.items]
            .map((item) => item.webkitGetAsEntry?.() as unknown as EntryLike | null)
            .filter((entry): entry is EntryLike => entry !== null);
          const files = withPaths(event.dataTransfer.files);
          void (entries.length > 0 ? readDroppedEntries(entries) : Promise.resolve(files))
            .then(accept)
            .catch(() =>
              setResult({
                kind: "error",
                message: "读不出拖入的内容，请点\u201c选择技能文件夹\u201d",
              }),
            );
        }}
      >
        <Upload className="size-5" />
        <p>把技能文件夹、.zip 或 SKILL.md 拖到这里；文件夹或压缩包里要有 SKILL.md</p>
        <div className="flex gap-2">
          <label className="cursor-pointer border border-border px-2.5 py-1 font-mono text-xs text-foreground hover:bg-accent">
            选择技能文件夹
            <input
              type="file"
              multiple
              className="sr-only"
              {...FOLDER_PICKER}
              onChange={(event) => void accept(withPaths(event.target.files))}
            />
          </label>
          <label className="cursor-pointer border border-border px-2.5 py-1 font-mono text-xs text-foreground hover:bg-accent">
            选择文件
            <input
              type="file"
              accept=".zip,.md"
              className="sr-only"
              onChange={(event) => void accept(withPaths(event.target.files))}
            />
          </label>
        </div>
      </div>
      {result?.kind === "ok" && (
        <dl className="grid grid-cols-[4rem_1fr] gap-x-3 gap-y-1 border border-border p-3 text-sm">
          <dt className="text-muted-foreground">名称</dt>
          <dd>{result.name}</dd>
          <dt className="text-muted-foreground">描述</dt>
          <dd>{result.description}</dd>
          <dt className="text-muted-foreground">文件数</dt>
          <dd>{result.fileCount}</dd>
        </dl>
      )}
      {result?.kind === "zip" && (
        <p className="text-sm text-muted-foreground">{result.fileName}：压缩包会在安装时检查</p>
      )}
      {result?.kind === "error" && <p className="text-sm text-danger">{result.message}</p>}
      {failure && <p className="text-sm text-danger">{failure}</p>}
    </Modal>
  );
}
