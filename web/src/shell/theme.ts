/** Light/dark theme: follows the system until the visitor picks one, then remembers it. */

export type Theme = "light" | "dark";
const KEY = "rondo-theme";

export function currentTheme(): Theme {
  const set = document.documentElement.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Private windows can block storage; the choice then lasts for this page view only.
  }
}
