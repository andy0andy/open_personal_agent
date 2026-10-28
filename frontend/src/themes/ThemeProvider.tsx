import {
  createContext,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { applyTheme } from "./apply";
import {
  browserStorage,
  loadPreference,
  resolveMode,
  savePreference,
  type ModePreference,
} from "./mode";
import { DEFAULT_THEME } from "./registry";
import type { ColorMode } from "./types";

interface ThemeContextValue {
  preference: ModePreference;
  mode: ColorMode;
  setPreference: (preference: ModePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const DARK_QUERY = "(prefers-color-scheme: dark)";

function subscribeSystemMode(onChange: () => void): () => void {
  const media = window.matchMedia(DARK_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

const systemPrefersDark = () => window.matchMedia(DARK_QUERY).matches;

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ModePreference>(() =>
    loadPreference(browserStorage()),
  );
  const prefersDark = useSyncExternalStore(subscribeSystemMode, systemPrefersDark);
  const mode = resolveMode(preference, prefersDark);

  useEffect(() => {
    applyTheme(document.documentElement, DEFAULT_THEME, mode);
  }, [mode]);

  const setPreference = (next: ModePreference) => {
    setPreferenceState(next);
    savePreference(browserStorage(), next);
  };

  return <ThemeContext value={{ preference, mode, setPreference }}>{children}</ThemeContext>;
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme 必须在 ThemeProvider 内使用");
  return value;
}
