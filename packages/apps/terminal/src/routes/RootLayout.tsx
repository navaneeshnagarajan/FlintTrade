import { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { useThemeStore } from "@/stores/themeStore";
import { AITutorPill } from "@/components/help/AITutorPill";
import { UpgradeSuggestionHost } from "@/components/help/UpgradeSuggestion";

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
  "/ai": "AI Centre",
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
  // Apply theme CSS properties on initial mount and whenever the active theme changes.
  // themeStore.setTheme() already calls applyTheme() on user changes; this ensures
  // the correct theme is applied when the app first loads from persisted state.
  const applyTheme = useThemeStore((s) => s.applyTheme);

  useDocumentTitle();

  useEffect(() => {
    applyTheme();
  }, [applyTheme]);

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
