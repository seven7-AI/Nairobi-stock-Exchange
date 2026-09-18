// Chart colours: the validated categorical order from the dataviz reference palette,
// assigned in fixed order (never cycled), plus the status set. Light/dark values are
// selected steps of the same hues, not an automatic flip.
export const SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"] as const;
export const SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"] as const;

export const STATUS = { good: "#0ca30c", warning: "#fab219", serious: "#ec835a", critical: "#d03b3b" } as const;

export function isDark(): boolean {
  if (typeof window === "undefined") return false;
  const stamp = document.documentElement.dataset.theme;
  if (stamp === "dark") return true;
  if (stamp === "light") return false;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

export function series(index: number): string {
  const set = isDark() ? SERIES_DARK : SERIES_LIGHT;
  return set[Math.min(index, set.length - 1)];
}

export const CHROME = {
  grid: { light: "#e1e0d9", dark: "#2c2c2a" },
  axis: { light: "#c3c2b7", dark: "#383835" },
  muted: "#898781",
  gap: { light: "rgba(137,135,129,0.18)", dark: "rgba(137,135,129,0.28)" },
} as const;

export function chrome(key: "grid" | "axis" | "gap"): string {
  return CHROME[key][isDark() ? "dark" : "light"];
}
