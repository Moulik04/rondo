import { useState } from "react";
import { applyTheme, currentTheme, type Theme } from "./theme";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(currentTheme);
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="theme-toggle"
      aria-label={`Switch to ${next} theme`}
      onClick={() => {
        applyTheme(next);
        setTheme(next);
      }}
    >
      <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
        <circle cx="10" cy="10" r="7.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <path d="M10 2.5a7.5 7.5 0 0 1 0 15z" fill="currentColor" />
      </svg>
      <span className="theme-toggle__label">{theme === "dark" ? "Dark" : "Light"}</span>
    </button>
  );
}
