import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { ReactNode } from "react";

const searchSymbolMock = vi.hoisted(() => vi.fn());

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => {
      const safe = { ...props };
      for (const key of ["initial", "animate", "exit", "variants", "transition", "layoutId"]) {
        delete safe[key];
      }
      return <div {...safe}>{children as ReactNode}</div>;
    },
  },
  AnimatePresence: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/services/api", () => ({
  searchSymbol: searchSymbolMock,
}));
vi.mock("@/components/DocsSearch/DocsSearch", () => ({
  default: () => null,
  searchDocs: vi.fn().mockResolvedValue([]),
}));
vi.mock("@/stores/themeStore", () => ({
  useThemeStore: (selector: (state: Record<string, unknown>) => unknown) =>
    selector({ setTheme: vi.fn(), setMode: vi.fn(), mode: "dark" }),
}));
vi.mock("@/hooks/useSkillLevel", () => ({ useSkillLevel: () => "advanced" }));
vi.mock("@/layout/widgetFactory", () => ({ widgetCatalog: [] }));

vi.mock("@/chrome/TopBarV2", () => ({ default: () => null }));
vi.mock("@/chrome/DockSidebar", () => ({ default: () => null }));
vi.mock("@/chrome/TickerBar", () => ({ default: () => null }));
vi.mock("@/components/motion/PageTransition", () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/welcome/DailyWelcome", () => ({ default: () => null }));
vi.mock("@/components/NoConnectionOverlay", () => ({ NoConnectionOverlay: () => null }));
vi.mock("@/components/LockScreen", () => ({ LockScreen: () => null }));
vi.mock("@/components/KeyboardShortcuts/KeyboardShortcutsDialog", () => ({ default: () => null }));
vi.mock("@/components/Changelog/ChangelogViewer", () => ({ default: () => null }));
vi.mock("@/hooks/useWsBridge", () => ({ useWsBridge: vi.fn() }));
vi.mock("@/hooks/useDemoFeed", () => ({ useDemoFeed: vi.fn() }));
vi.mock("@/hooks/useTickerFallback", () => ({ useTickerFallback: vi.fn() }));
vi.mock("@/hooks/usePrevClose", () => ({ usePrevClose: vi.fn() }));
vi.mock("@/hooks/useOpenAlgoConfigHydration", () => ({ useOpenAlgoConfigHydration: vi.fn() }));
vi.mock("@/hooks/useTradingStoreSync", () => ({ useTradingStoreSync: vi.fn() }));
vi.mock("@/hooks/useBrokerAccounts", () => ({ useBrokerAccounts: vi.fn() }));
vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({ useNotificationFeed: vi.fn() }));
vi.mock("@/hooks/useGlobalKeys", () => ({ default: vi.fn() }));
vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (state: Record<string, unknown>) => unknown) => selector({ mode: "live" }),
}));
vi.mock("@/stores/authStore", () => ({
  useAuthStore: Object.assign(
    (selector: (state: Record<string, unknown>) => unknown) => selector({ status: "logged-in" }),
    { getState: () => ({ checkIdle: vi.fn(), touchActivity: vi.fn() }) },
  ),
}));
vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: (selector: (state: Record<string, unknown>) => unknown) => selector({ apiKey: "" }),
}));
vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: (selector: (state: Record<string, unknown>) => unknown) => selector({ workspaceApi: null }),
}));

import AppLayout from "../AppLayout";

function LocationProbe() {
  const location = useLocation();
  return <output aria-label="Current route">{location.pathname}{location.search}</output>;
}

function renderJourney() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/trade"]}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="trade" element={<LocationProbe />} />
            <Route path="ai" element={<LocationProbe />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AI symbol context journey", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    localStorage.clear();
    Object.defineProperty(window, "innerWidth", { value: 1920, writable: true });
    searchSymbolMock.mockResolvedValue([{ symbol: "RELIANCE", exchange: "NSE" }]);
  });

  it("routes a real validated CommandPalette result to the encoded /ai context URL", async () => {
    renderJourney();
    act(() => {
      window.dispatchEvent(new CustomEvent("flinttrade:open-command-palette"));
    });

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "reliance" } });
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /reliance/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask AI about RELIANCE" }));

    expect(await screen.findByRole("status", { name: "Current route" })).toHaveTextContent(
      "/ai?symbol=RELIANCE&exchange=NSE&source=palette",
    );
  });
});
