import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { useSettingsStore } from "@/stores/settingsStore";

const THEME_CLASSES = [
  "theme-obsidian",
  "theme-terminal-green",
  "theme-ocean-blue",
  "theme-light",
] as const;

export default function RootLayout() {
  const theme = useSettingsStore((s) => s.theme);

  useEffect(() => {
    const html = document.documentElement;
    // Remove all theme classes
    html.classList.remove(...THEME_CLASSES);
    // Add current theme (midnight has no class — it's the default :root values)
    if (theme !== "midnight") {
      html.classList.add(`theme-${theme}`);
    }
  }, [theme]);

  return <Outlet />;
}
