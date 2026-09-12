import { useEffect, useLayoutEffect, useState } from "react";

const key = "themis-trial-theme";
type Theme = "light" | "dark";
function initialPreference(): { theme: Theme; manual: boolean } {
  try {
    const stored = localStorage.getItem(key);
    if (stored === "light" || stored === "dark")
      return { theme: stored, manual: true };
  } catch {
    /* Storage may be disabled; the toggle still works in memory. */
  }
  return {
    theme: window.matchMedia?.("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light",
    manual: false,
  };
}

export function ThemeToggle() {
  const [preference, setPreference] = useState(initialPreference);
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = preference.theme;
  }, [preference.theme]);
  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!media || preference.manual) return;
    const update = () =>
      setPreference({ theme: media.matches ? "dark" : "light", manual: false });
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [preference.manual]);
  function toggle() {
    const theme = preference.theme === "dark" ? "light" : "dark";
    setPreference({ theme, manual: true });
    try {
      localStorage.setItem(key, theme);
    } catch {
      /* No evidence is stored. */
    }
  }
  return (
    <button
      className="theme-toggle"
      onClick={toggle}
      aria-pressed={preference.theme === "dark"}
      aria-label="Dark mode"
    >
      <span aria-hidden="true">{preference.theme === "dark" ? "☾" : "☀"}</span>
      {preference.theme === "dark" ? "Dark" : "Light"} mode
    </button>
  );
}
