import { useQuery } from "@tanstack/react-query";
import { Cpu, TriangleAlert } from "lucide-react";
import { readableError } from "../../api/client";
import { modelsQuery } from "../../api/queries";

/** 输入框下方工具条里的模型选择：改了立即存到会话上（由调用方保存）。 */
export function ModelSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (model: string) => void;
}) {
  const models = useQuery(modelsQuery);
  const chatModels = (models.data ?? []).filter((model) => model.mode === "chat");

  if (models.isError && !models.data) {
    return (
      <span
        className="flex items-center gap-1.5 text-xs text-danger"
        title={readableError(models.error)}
      >
        <TriangleAlert className="size-3.5" />
        模型列表加载失败，正在重试…
      </span>
    );
  }

  return (
    <label
      className="flex min-w-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted focus-within:ring-1 focus-within:ring-ring"
      title="这个会话用的模型"
    >
      <Cpu className="size-3.5 shrink-0" />
      <select
        aria-label="会话的模型"
        className="max-w-40 min-w-0 truncate bg-transparent font-mono text-xs text-foreground outline-none"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {!chatModels.some((model) => model.name === value) && (
          <option value={value}>{value}</option>
        )}
        {chatModels.map((model) => (
          <option key={model.name} value={model.name}>
            {model.name}
          </option>
        ))}
      </select>
    </label>
  );
}
