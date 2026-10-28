import { Monitor, Moon, Sun } from "lucide-react";
import type { ModePreference } from "../../themes/mode";
import { useTheme } from "../../themes/ThemeProvider";

const OPTIONS: { value: ModePreference; label: string; Icon: typeof Sun }[] = [
  { value: "system", label: "跟随系统", Icon: Monitor },
  { value: "dark", label: "深色", Icon: Moon },
  { value: "light", label: "浅色", Icon: Sun },
];

/** 外观切换：跟随系统 / 深色 / 浅色。侧栏只显示图标时（窄于 1280px）三个按钮竖着排。 */
export function AppearanceToggle() {
  const { preference, setPreference } = useTheme();
  return (
    <div
      role="radiogroup"
      aria-label="外观"
      className="flex flex-col rounded-lg border border-border bg-card p-0.5 xl:flex-row"
    >
      {OPTIONS.map(({ value, label, Icon }) => (
        <button
          key={value}
          role="radio"
          aria-checked={preference === value}
          aria-label={label}
          title={label}
          onClick={() => setPreference(value)}
          className={`flex flex-1 items-center justify-center rounded-md py-1 transition-colors ${
            preference === value
              ? "bg-accent text-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <Icon className="size-3.5" aria-hidden="true" />
        </button>
      ))}
    </div>
  );
}
