import {
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";

// 输入框边框比分隔线深（设计 2026-10-22 2.1）：看得出哪里能输入；聚焦框用全局的 :focus-visible
const BOX =
  "w-full rounded-lg border border-input bg-background px-2.5 text-sm disabled:opacity-50";
const INPUT = `${BOX} h-9`;

/** 表单里带标签与错误提示的一项：标签与输入框关联，读屏与"按标签找输入框"都能用。 */
export function TextField({
  label,
  error,
  hint,
  multiline = false,
  value,
  onChange,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> & {
  label: string;
  error?: string;
  hint?: ReactNode;
  multiline?: boolean;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  const noteId = `${id}-note`;
  // 读屏读得到错误与提示：输入框指向下面那行字，出错时标为无效（积压小问题 H2）
  const described = {
    ...((hint || error) && { "aria-describedby": noteId }),
    ...(error && { "aria-invalid": true }),
  };
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-xs text-muted-foreground">
        {label}
      </label>
      {multiline ? (
        <textarea
          id={id}
          className={`${BOX} min-h-24 py-2 font-mono`}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          {...(props as TextareaHTMLAttributes<HTMLTextAreaElement>)}
          {...described}
        />
      ) : (
        <input
          id={id}
          className={INPUT}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          {...props}
          {...described}
        />
      )}
      {hint && !error && (
        <p id={noteId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={noteId} className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: readonly string[];
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-xs text-muted-foreground">
        {label}
      </label>
      <select
        id={id}
        className={INPUT}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </div>
  );
}
