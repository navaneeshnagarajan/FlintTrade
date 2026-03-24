import { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { useSettingsStore } from "@/stores/settingsStore";
import { AITutorPill } from "@/components/help/AITutorPill";
import { UpgradeSuggestionHost } from "@/components/help/UpgradeSuggestion";

const THEME_CLASSES = [
  "theme-obsidian",
  "theme-terminal-green",
  "theme-ocean-blue",
  "theme-light",
] as const;

const ROUTE_TITLES: Record<string, string> = {
  "/welcome": "Welcome",
  "/explore": "Explore",
  "/setup": "Setup",
  "/settings": "Settings",
  "/trade": "Trade",
  "/invest": "Invest",
  "/learn": "Learn",
  "/lab": "Strategy Lab",
  "/automate": "Automate",
  "/ai": "AI Center",
};

function useDocumentTitle() {
  const { pathname } = useLocation();
  useEffect(() => {
    const base = "/" + pathname.split("/")[1];
    const title = ROUTE_TITLES[base] ?? "FlintTrade";
    document.title = title === "FlintTrade" ? title : `${title} | FlintTrade`;
  }, [pathname]);
}

export default function RootLayout() {
  const theme = useSettingsStore((s) => s.theme);

  useDocumentTitle();

  useEffect(() => {
    const html = document.documentElement;
    // Remove all theme classes
    html.classList.remove(...THEME_CLASSES);
    // Add current theme (midnight has no class — it's the default :root values)
    if (theme !== "midnight") {
      html.classList.add(`theme-${theme}`);
    }
  }, [theme]);

  return (
    <>
      <Outlet />
      {/* AITutorPill is rendered here so it appears on every route including /welcome and /explore */}
      <AITutorPill />
      {/* UpgradeSuggestionHost polls for upgrade suggestions every 60 s */}
      <UpgradeSuggestionHost />
    </>
  );
}
