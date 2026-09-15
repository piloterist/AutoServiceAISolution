"use client";

import { useEffect, useState } from "react";

type ThemeChoice = "light" | "dark" | null; // null = follow system preference

const STORAGE_KEY = "theme";

/** Clicking an already-active button turns it back off (falls back to
 * `prefers-color-scheme`) - so this is a 3-state control (light/dark/
 * system), not a plain on/off switch. See globals.css for the actual
 * three-state token contract this drives (`[data-theme]` + media query). */
export function ThemeToggle() {
  const [theme, setTheme] = useState<ThemeChoice>(null);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === "light" || stored === "dark") setTheme(stored);
    } catch {
      // localStorage unavailable (private browsing etc.) - just stay on
      // "system".
    }
  }, []);

  const apply = (next: ThemeChoice) => {
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next ?? "");
    if (!next) document.documentElement.removeAttribute("data-theme");
    try {
      if (next) window.localStorage.setItem(STORAGE_KEY, next);
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Ignore - the attribute is already applied, storage is best-effort.
    }
  };

  return (
    <div className="theme-toggle" role="group" aria-label="Тема оформления">
      <button
        type="button"
        className={theme === "light" ? "theme-toggle-btn theme-toggle-btn-active" : "theme-toggle-btn"}
        onClick={() => apply(theme === "light" ? null : "light")}
        aria-label="Светлая тема"
        title="Светлая тема"
      >
        ☀️
      </button>
      <button
        type="button"
        className={theme === "dark" ? "theme-toggle-btn theme-toggle-btn-active" : "theme-toggle-btn"}
        onClick={() => apply(theme === "dark" ? null : "dark")}
        aria-label="Тёмная тема"
        title="Тёмная тема"
      >
        🌙
      </button>
    </div>
  );
}
