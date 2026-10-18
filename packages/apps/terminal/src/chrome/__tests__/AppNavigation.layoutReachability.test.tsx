import { useState } from "react";
import { act, cleanup, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AppLayout from "@/routes/AppLayout";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useCommandRegistry } from "@/components/CommandPalette/useCommandRegistry";
import { readAppLayouts } from "@/layout/appLayouts";

// Keep the mounted shell, navigation, retained host, app toolbar, factory and
// FlexLayout real. Only unrelated chrome/transports and expensive leaves are
// inert; More-sheet behaviour stays in TopBarV2's original maintained suite.
vi.mock("@/chrome/TopBarV2", () => ({ default: () => null }));
vi.mock("@/chrome/TickerBar", () => ({ default: () => null }));
vi.mock("@/components/NoConnectionOverlay", () => ({ NoConnectionOverlay: () => null }));
vi.mock("@/hooks/useWsBridge", () => ({ useWsBridge: vi.fn() }));
vi.mock("@/hooks/useDemoFeed", () => ({ useDemoFeed: vi.fn() }));
vi.mock("@/hooks/useTickerFallback", () => ({ useTickerFallback: vi.fn() }));
vi.mock("@/hooks/usePrevClose", () => ({ usePrevClose: vi.fn() }));
vi.mock("@/hooks/useTradingStoreSync", () => ({ useTradingStoreSync: vi.fn() }));
vi.mock("@/hooks/useBrokerAccounts", () => ({ useBrokerAccounts: vi.fn() }));
vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({ useNotificationFeed: vi.fn() }));
vi.mock("@/lib/instrumentLots", () => ({ loadInstrumentLotRows: vi.fn() }));
vi.mock("@/routes/TerminalRoute", () => ({ KillSwitchPill: () => null }));
vi.mock("@/chrome/InstrumentLinks", () => ({ InstrumentLinks: () => null }));
vi.mock("@/routes/SetupAccountRoute", () => ({ PracticeLaterSetup: () => null }));
vi.mock("@/routes/SettingsRoute", () => ({ default: () => <Draft name="Settings" /> }));
vi.mock("@/routes/LearnRoute", () => ({ default: () => <Draft name="Learn" /> }));
vi.mock("@/components/help/KnowledgeSelector", () => ({ default: () => <p>Knowledge leaf</p> }));
function Draft({ name }: { name: string }) {
  const [value, setValue] = useState("");
  return <label>{name} navigation canary<input value={value} onChange={event => setValue(event.target.value)} /></label>;
}
const expectedApps = [
  ["Terminal", "/terminal"], ["Testing", "/testing"], ["Portfolio", "/portfolio"],
  ["Automation", "/automation"], ["Reports", "/reports"], ["Learn", "/learn"],
  ["Brokers", "/brokers"], ["Settings", "/settings"], ["System", "/system"],
];
const unexpectedRequests: string[] = [];
let client: QueryClient;
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  unexpectedRequests.length = 0;
  useAuthStore.setState({ status: "logged-out", token: null });
  useModeStore.setState({ mode: "explore" });
  useConnectionStore.setState(useConnectionStore.getInitialState());
  useBrokerStore.setState(useBrokerStore.getInitialState());
  vi.stubGlobal("fetch", vi.fn(async (url: unknown) => {
    unexpectedRequests.push(String(url));
    throw new Error(`Unexpected compact-navigation transport: ${String(url)}`);
  }));
  Object.defineProperty(window, "innerWidth", { value: 390, configurable: true });
  const rect = { x: 0, y: 0, width: 390, height: 600, top: 0, left: 0, right: 390, bottom: 600, toJSON: () => ({}) };
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(rect);
  vi.stubGlobal("ResizeObserver", class {
    constructor(private callback: ResizeObserverCallback) {}
    observe(target: Element) { this.callback([{ target, contentRect: rect } as ResizeObserverEntry], this as unknown as ResizeObserver); }
    unobserve() {}
    disconnect() {}
  });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
});
afterEach(() => {
  cleanup(); client.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  expect(unexpectedRequests).toEqual([]);
});
function renderShell() {
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/settings"]}><AppLayout /></MemoryRouter></QueryClientProvider>);
}

describe("compact app navigation and layout ownership", () => {
  it("keeps every app in accessible top navigation and focuses the newly selected app", async () => {
    renderShell();
    await screen.findByLabelText("Settings navigation canary");
    const nav = screen.getByRole("navigation", { name: "Apps" });
    expect(nav).toHaveClass("overflow-x-auto");
    expect(within(nav).getAllByRole("link").map(link => [link.textContent, link.getAttribute("href")])).toEqual(expectedApps);
    for (const link of within(nav).getAllByRole("link")) {
      expect(link).toHaveClass("shrink-0", "focus-visible:outline");
      expect(link).toBeVisible();
    }
    expect(within(nav).getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
    fireEvent.click(within(nav).getByRole("link", { name: "Learn" }));
    await screen.findByLabelText("Learn navigation canary");
    expect(within(nav).getByRole("link", { name: "Learn" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Settings" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("main", { name: "Learn" })).toHaveFocus();
    expect(screen.queryByTestId("nav-drawer-btn")).not.toBeInTheDocument();
  });

  it("reaches real compact layout controls and saves, resets and restores a named composition", async () => {
    renderShell();
    await screen.findByLabelText("Settings navigation canary");
    const app = within(screen.getByRole("region", { name: "Settings app" }));
    expect(app.getByRole("combobox", { name: "Settings preset" })).toBeEnabled();
    expect(app.getByRole("combobox", { name: "Compact panel" })).toBeEnabled();
    fireEvent.click(app.getByRole("button", { name: "Add widget" }));
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Settings widgets");
    fireEvent.click(screen.getByRole("button", { name: "Add Shared knowledge" }));
    await screen.findByText("Knowledge leaf");
    fireEvent.change(app.getByRole("textbox", { name: "Layout name" }), { target: { value: "Compact saved" } });
    fireEvent.click(app.getByRole("button", { name: "Save layout" }));
    expect(app.getByRole("status")).toHaveTextContent("Saved Compact saved");
    const saved = readAppLayouts("settings")["Compact saved"];
    expect(JSON.stringify(saved)).toContain('"component":"knowledge-library"');
    fireEvent.click(app.getByText("Layout actions"));
    expect(app.getByRole("button", { name: "Export layout" })).toBeVisible();
    expect(app.getByLabelText("Import app layout")).toBeVisible();
    fireEvent.click(app.getByRole("button", { name: "Reset app layout" }));
    expect(screen.queryByText("Knowledge leaf")).not.toBeInTheDocument();
    fireEvent.change(app.getByRole("combobox", { name: "Restore saved layout" }), { target: { value: "Compact saved" } });
    expect(await screen.findByText("Knowledge leaf")).toBeInTheDocument();
    expect(app.getByRole("status")).toHaveTextContent("Restored Compact saved");
    expect(readAppLayouts("settings")["Compact saved"]).toEqual(saved);
    expect(useAuthStore.getState().status).toBe("logged-out");
    expect(useBrokerStore.getState().activeAccountId).toBeNull();
    expect(useModeStore.getState().mode).toBe("explore");
  });

  it("routes a public reset command only to the active toolbar owner", async () => {
    renderShell();
    await screen.findByLabelText("Settings navigation canary");
    const nav = within(screen.getByRole("navigation", { name: "Apps" }));
    fireEvent.click(nav.getByRole("link", { name: "Learn" }));
    const draft = await screen.findByLabelText("Learn navigation canary");
    fireEvent.change(draft, { target: { value: "Retained hidden learning draft" } });
    fireEvent.click(nav.getByRole("link", { name: "Settings" }));
    await screen.findByLabelText("Settings navigation canary");
    fireEvent.click(screen.getByRole("button", { name: "Add widget" }));
    fireEvent.click(screen.getByRole("button", { name: "Add Shared knowledge" }));
    await screen.findByText("Knowledge leaf");
    const { result } = renderHook(() => useCommandRegistry());
    const reset = result.current.commands.find(command => command.id === "action:reset-layout");
    expect(reset).toBeDefined();
    act(() => { reset!.action(); });
    expect(screen.queryByText("Knowledge leaf")).not.toBeInTheDocument();
    expect(draft.isConnected).toBe(true);
    expect(draft).not.toBeVisible();
    fireEvent.click(nav.getByRole("link", { name: "Learn" }));
    expect(await screen.findByLabelText("Learn navigation canary")).toBe(draft);
    expect(draft).toHaveValue("Retained hidden learning draft");
  });
});
