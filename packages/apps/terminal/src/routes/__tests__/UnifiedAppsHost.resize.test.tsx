import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { UnifiedAppsHost } from "../UnifiedAppsHost";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";
import { captureOperatorIncidentScope } from "@/lib/operatorIncidentScope";

// Actual retained docking tree, Research, BacktestSection and TabTransition.
// Preview eligibility is fixed; no submitted job or authoritative backend data.
vi.mock("@/lib/demoSession", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/demoSession")>(), isPublicDemoBuild: () => true,
}));
vi.mock("@/routes/TerminalRoute", () => ({ KillSwitchPill: () => null }));
vi.mock("@/chrome/InstrumentLinks", () => ({ InstrumentLinks: () => null }));
vi.mock("@/routes/SetupAccountRoute", () => ({ PracticeLaterSetup: () => null }));
let geometry = { width: 390, height: 844 };
let reduced = false;
const mediaListeners = new Set<() => void>();
const observers = new Map<Element, ResizeObserverCallback>();
const unexpected: string[] = [];
let client: QueryClient;
function rect() { return { x: 0, y: 0, ...geometry, top: 0, left: 0, right: geometry.width, bottom: geometry.height, toJSON: () => ({}) }; }
beforeEach(() => {
  geometry = { width: 390, height: 844 }; reduced = false; observers.clear(); unexpected.length = 0; mediaListeners.clear();
  localStorage.clear(); sessionStorage.clear(); window.history.replaceState(null, "", "/testing");
  useAuthStore.setState({ status: "logged-out", token: null });
  useBrokerStore.setState(useBrokerStore.getInitialState());
  useConnectionStore.setState(useConnectionStore.getInitialState());
  useModeStore.setState({ mode: "explore" });
  vi.stubGlobal("fetch", vi.fn(async (url: unknown, init?: RequestInit) => {
    if (String(url) === "/ft-api/api/v1/backtest/strategies" && (!init?.method || init.method === "GET")) {
      return new Response(JSON.stringify({ status: "success", data: { strategies: [] } }));
    }
    unexpected.push(`${init?.method ?? "GET"} ${String(url)}`); throw new Error("Unexpected resize-test transport");
  }));
  vi.spyOn(window, "matchMedia").mockImplementation(query => ({
    get matches() { return query === "(prefers-reduced-motion: reduce)" && reduced; },
    media: query, onchange: null, addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: (_event: string, listener: () => void) => { if (query === "(prefers-reduced-motion: reduce)") mediaListeners.add(listener); },
    removeEventListener: (_event: string, listener: () => void) => mediaListeners.delete(listener), dispatchEvent: () => false,
  }) as unknown as MediaQueryList);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(rect);
  vi.stubGlobal("ResizeObserver", class {
    private targets = new Set<Element>();
    constructor(private callback: ResizeObserverCallback) {}
    observe(target: Element) { this.targets.add(target); observers.set(target, this.callback); this.callback([{ target, contentRect: rect() } as ResizeObserverEntry], this as unknown as ResizeObserver); }
    unobserve(target: Element) { this.targets.delete(target); observers.delete(target); }
    disconnect() { for (const target of this.targets) observers.delete(target); this.targets.clear(); }
  });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
});
afterEach(() => { cleanup(); client.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); expect(unexpected).toEqual([]); });
async function resize(width: number, height: number) {
  await act(async () => {
    geometry = { width, height };
    for (const [target, callback] of [...observers]) callback([{ target, contentRect: rect() } as ResizeObserverEntry], {} as ResizeObserver);
    window.dispatchEvent(new Event("resize"));
  });
}
function mount() { render(<QueryClientProvider client={client}><BrowserRouter><Link to="/settings">Settings app</Link><Link to="/testing">Testing app</Link><UnifiedAppsHost /></BrowserRouter></QueryClientProvider>); }

it.each([false, true])("retains the real unsubmitted Backtest draft through all native geometry directions with constant reduced-motion=%s", async preference => {
  reduced = preference; mount();
  const input = await screen.findByPlaceholderText("NIFTY");
  fireEvent.change(input, { target: { value: "RESIZE-CANARY" } });
  const scope = captureOperatorIncidentScope();
  for (const [width, height] of [[370, 824], [1440, 1000], [390, 844]]) {
    await resize(width, height);
    expect(await screen.findByPlaceholderText("NIFTY")).toBe(input);
    expect(input).toHaveValue("RESIZE-CANARY");
    expect(captureOperatorIncidentScope()).toEqual(scope);
    await vi.waitFor(() => expect(screen.getByText("No results yet")).toBeVisible());
  }
});

it.each([false, true])("retains the actual Backtest child immediately on live media callbacks from reduced=%s", async initial => {
  reduced = initial; mount();
  const input = await screen.findByPlaceholderText("NIFTY");
  fireEvent.change(input, { target: { value: "LIVE-MEDIA-CANARY" } });
  const scope = captureOperatorIncidentScope();
  for (const preference of [!initial, initial]) {
    await act(async () => { reduced = preference; for (const listener of mediaListeners) listener(); });
    expect(screen.getByPlaceholderText("NIFTY")).toBe(input);
    expect(input).toHaveValue("LIVE-MEDIA-CANARY");
    expect(captureOperatorIncidentScope()).toEqual(scope);
  }
});

it("retains the real Backtest draft after motion preference changes and the retained app next renders", async () => {
  reduced = true; mount();
  const input = await screen.findByPlaceholderText("NIFTY");
  fireEvent.change(input, { target: { value: "MEDIA-RESIZE-CANARY" } });
  const scope = captureOperatorIncidentScope();
  // A native resize was the original trigger. Minimise to the next real
  // retained-view render after the changed native motion preference.
  reduced = false;
  fireEvent.click(screen.getByRole("link", { name: "Settings app" }));
  await screen.findByRole("region", { name: "Settings app" });
  fireEvent.click(screen.getByRole("link", { name: "Testing app" }));
  expect(captureOperatorIncidentScope()).toEqual(scope);
  expect(await screen.findByPlaceholderText("NIFTY")).toHaveValue("MEDIA-RESIZE-CANARY");
  expect(screen.getByPlaceholderText("NIFTY")).toBe(input);
});
