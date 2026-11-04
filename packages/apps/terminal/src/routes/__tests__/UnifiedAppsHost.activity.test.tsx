import { useEffect, useState } from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { BrowserRouter, Link } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterAll, afterEach, beforeEach, expect, it, vi } from "vitest";
import { UnifiedAppsHost } from "../UnifiedAppsHost";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { captureOperatorIncidentScope } from "@/lib/operatorIncidentScope";
import { buildAppPreset, readAppLayouts, saveAppLayout } from "@/layout/appLayouts";

// Keep the real router, host, route, FlexLayout and appWidgetFactory. Only the
// expensive leaf tools are inert lifecycle canaries; canonical real-client
// retirement and scope/privacy fences have their own integrated regressions.
const events = vi.hoisted(() => [] as string[]);
function Tool({ name }: { name: string }) {
  const [draft, setDraft] = useState("");
  useEffect(() => {
    events.push(`open:${name}`);
    const work = () => events.push(`work:${name}`);
    window.addEventListener("r43:work", work);
    return () => { events.push(`close:${name}`); window.removeEventListener("r43:work", work); };
  }, [name]);
  return <label>{name} inner draft<input value={draft} onChange={event => setDraft(event.target.value)} /></label>;
}
vi.mock("@/routes/LearnRoute", () => ({ default: () => <Tool name="Learn" /> }));
vi.mock("@/routes/SettingsRoute", () => ({ default: () => <Tool name="Settings" /> }));
vi.mock("@/routes/TerminalRoute", () => ({ KillSwitchPill: () => null }));
vi.mock("@/chrome/InstrumentLinks", () => ({ InstrumentLinks: () => null }));
vi.mock("@/routes/SetupAccountRoute", () => ({ PracticeLaterSetup: () => null }));

// Only the native drawing engine is inert: the real Chart, Welcome, Positions
// and Calculator leaves still run through the router/docking/lazy factories.
vi.mock("lightweight-charts", async importOriginal => ({
  ...await importOriginal<typeof import("lightweight-charts")>(),
  createChart: () => {
    const scale = { fitContent: vi.fn(), applyOptions: vi.fn(), setVisibleLogicalRange: vi.fn(),
      getVisibleLogicalRange: () => null, subscribeVisibleLogicalRangeChange: vi.fn(),
      unsubscribeVisibleLogicalRangeChange: vi.fn(), subscribeVisibleTimeRangeChange: vi.fn(),
      unsubscribeVisibleTimeRangeChange: vi.fn(), setVisibleRange: vi.fn(),
      timeToCoordinate: () => null, coordinateToTime: () => null };
    return { applyOptions: vi.fn(), remove: vi.fn(), resize: vi.fn(),
      subscribeCrosshairMove: vi.fn(), unsubscribeCrosshairMove: vi.fn(),
      subscribeClick: vi.fn(), unsubscribeClick: vi.fn(), timeScale: () => scale,
      priceScale: () => scale, panes: () => [], removeSeries: vi.fn(),
      addSeries: () => ({ setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn(),
        attachPrimitive: vi.fn(), detachPrimitive: vi.fn(), priceScale: () => scale,
        priceToCoordinate: () => null, coordinateToPrice: () => null }),
    };
  },
  createSeriesMarkers: () => ({ setMarkers: vi.fn(), detach: vi.fn() }),
}));
let client: QueryClient;
const transportAttempts: string[] = [];
let geometry = { width: 1024, height: 700 };
const resizeObservers = new Map<Element, ResizeObserverCallback>();
function measure() {
  return { x: 0, y: 0, ...geometry, top: 0, left: 0, right: geometry.width, bottom: geometry.height, toJSON: () => ({}) };
}

beforeEach(() => {
  geometry = { width: 1024, height: 700 };
  resizeObservers.clear();
  events.length = 0;
  transportAttempts.length = 0;
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  useAuthStore.setState(useAuthStore.getInitialState());
  useBrokerStore.setState(useBrokerStore.getInitialState());
  useConnectionStore.setState(useConnectionStore.getInitialState());
  useModeStore.setState({ mode: "explore" });
  vi.stubGlobal("fetch", vi.fn(async (url: unknown, init?: RequestInit) => {
    transportAttempts.push(`${init?.method ?? "GET"} ${String(url)}`);
    throw new Error("Unexpected Activity fixture transport");
  }));
  localStorage.clear();
  window.history.replaceState(null, "", "/settings");
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(measure);
  vi.stubGlobal("ResizeObserver", class {
    private targets = new Set<Element>();
    constructor(private callback: ResizeObserverCallback) {}
    observe(target: Element) {
      this.targets.add(target);
      resizeObservers.set(target, this.callback);
      this.callback([{ target, contentRect: measure() } as ResizeObserverEntry], this as unknown as ResizeObserver);
    }
    unobserve(target: Element) { this.targets.delete(target); resizeObservers.delete(target); }
    disconnect() { for (const target of this.targets) resizeObservers.delete(target); this.targets.clear(); }
  });
});
afterEach(() => {
  cleanup(); client.clear(); localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  expect(transportAttempts).toEqual([]);
});
// Lazy module completion can outlive unmount. Drain after the suite's final
// cleanup, inside act, before Vitest snapshots and closes its worker RPCs.
// A per-test drain would change which unrelated lazy leaves mount next time.
afterAll(async () => { await act(async () => { await vi.dynamicImportSettled(); }); });

it.each([
  [390, 844, 370, 824],
  [390, 844, 1440, 1000],
  [1440, 1000, 390, 844],
])("retains the actual widget and its unsubmitted draft on geometry change %i×%i → %i×%i", async (width, height, nextWidth, nextHeight) => {
  geometry = { width, height };
  render(<BrowserRouter><UnifiedAppsHost /></BrowserRouter>);
  const input = await screen.findByLabelText("Settings inner draft");
  fireEvent.change(input, { target: { value: "RESIZE-CANARY" } });
  const app = screen.getByRole("region", { name: "Settings app" });
  await act(async () => {
    geometry = { width: nextWidth, height: nextHeight };
    for (const [target, callback] of [...resizeObservers]) {
      callback([{ target, contentRect: measure() } as ResizeObserverEntry], {} as ResizeObserver);
    }
    window.dispatchEvent(new Event("resize"));
  });
  expect(screen.getByRole("region", { name: "Settings app" })).toBe(app);
  expect(await screen.findByLabelText("Settings inner draft")).toHaveValue("RESIZE-CANARY");
  expect(screen.getByLabelText("Settings inner draft")).toBe(input);
  expect(events).toEqual(["open:Settings"]);
});

it("persists a restored model before any subsequent docking action or unmount", async () => {
  const named = buildAppPreset("settings", "default");
  named.layout.id = "named-layout-root";
  saveAppLayout("settings", "Named", named);
  render(<BrowserRouter><UnifiedAppsHost /></BrowserRouter>);
  await screen.findByLabelText("Settings inner draft");
  fireEvent.click(screen.getByText("Layout actions"));
  fireEvent.change(screen.getByLabelText("Restore saved layout"), { target: { value: "Named" } });
  expect(screen.getByRole("status")).toHaveTextContent("Restored Named");
  // Reading before unmount catches the old effect cleanup writing the PREVIOUS
  // model to Current while the restored model was only visible in memory.
  expect(readAppLayouts("settings").Current.layout.id).toBe("named-layout-root");
  expect(readAppLayouts("settings").Named).toEqual(named);
});

it("retains both actual factory leaves while only the visible app owns effects and global layout commands", async () => {
  const view = render(<BrowserRouter><Link to="/learn">Learn app</Link><Link to="/settings">Settings app</Link><UnifiedAppsHost /></BrowserRouter>);
  const settingsInput = await screen.findByLabelText("Settings inner draft");
  fireEvent.change(settingsInput, { target: { value: "Settings local" } });
  fireEvent.click(screen.getByText("Layout actions"));
  const settingsLayout = within(screen.getByRole("region", { name: "Settings app" })).getByLabelText("Layout name");
  fireEvent.change(settingsLayout, { target: { value: "Settings layout" } });
  fireEvent.click(screen.getByRole("link", { name: "Learn app" }));
  const learnInput = await screen.findByLabelText("Learn inner draft");
  fireEvent.change(learnInput, { target: { value: "Learn local" } });
  expect(settingsInput.isConnected).toBe(true);
  expect(settingsInput).not.toBeVisible();
  expect(events).toEqual(["open:Settings", "close:Settings", "open:Learn"]);
  act(() => { window.dispatchEvent(new Event("r43:work")); });
  expect(events.at(-1)).toBe("work:Learn");

  fireEvent.click(screen.getByRole("link", { name: "Settings app" }));
  await screen.findByLabelText("Settings inner draft");
  expect(screen.getByLabelText("Settings inner draft")).toBe(settingsInput);
  expect(settingsInput).toHaveValue("Settings local");
  expect(learnInput.isConnected).toBe(true);
  expect(learnInput).not.toBeVisible();
  act(() => { window.dispatchEvent(new Event("r43:work")); });
  expect(events.slice(-3)).toEqual(["close:Learn", "open:Settings", "work:Settings"]);

  // A command for the active app must not be delivered to a retained hidden
  // docking owner. Resetting the hidden Learn model would destroy its draft.
  act(() => { window.dispatchEvent(new Event("flinttrade:reset-layout")); });
  fireEvent.click(screen.getByRole("link", { name: "Learn app" }));
  expect(await screen.findByLabelText("Learn inner draft")).toBe(learnInput);
  expect(learnInput).toHaveValue("Learn local");
  view.unmount();
  expect(settingsInput.isConnected).toBe(false);
  expect(learnInput.isConnected).toBe(false);
  const stopped = events.length;
  act(() => { window.dispatchEvent(new Event("r43:work")); });
  expect(events).toHaveLength(stopped);
});

it.each(["account", "session", "backend", "mode", "account round trip"])("retains independent widget and layout drafts across hidden canonical scope retirement: %s", async change => {
  useAuthStore.setState({ status: "logged-in", token: "synthetic-host-A", username: "synthetic", sessionGeneration: 100 });
  useBrokerStore.setState({ activeAccountId: "native:synthetic:A" });
  useConnectionStore.setState({ apiKey: "synthetic-backend-A" });
  useModeStore.setState({ mode: "practice" });
  render(<BrowserRouter><Link to="/learn">Learn app</Link><Link to="/settings">Settings app</Link><UnifiedAppsHost /></BrowserRouter>);
  const settings = await screen.findByLabelText("Settings inner draft");
  fireEvent.change(settings, { target: { value: "unrelated local preference" } });
  fireEvent.click(screen.getByText("Layout actions"));
  const layout = within(screen.getByRole("region", { name: "Settings app" })).getByLabelText("Layout name");
  fireEvent.change(layout, { target: { value: "presentation layout" } });
  fireEvent.click(screen.getByRole("link", { name: "Learn app" }));
  const learn = await screen.findByLabelText("Learn inner draft");
  fireEvent.change(learn, { target: { value: "independent learning draft" } });
  const before = captureOperatorIncidentScope();
  await act(async () => {
    if (change.startsWith("account")) useBrokerStore.setState({ activeAccountId: "native:synthetic:B" });
    if (change === "account round trip") useBrokerStore.setState({ activeAccountId: "native:synthetic:A" });
    if (change === "session") useAuthStore.setState({ sessionGeneration: 101, token: "synthetic-host-B" });
    if (change === "backend") useConnectionStore.setState({ apiKey: "synthetic-backend-B" });
    if (change === "mode") useModeStore.setState({ mode: "live" });
  });
  expect(captureOperatorIncidentScope().generation).toBeGreaterThan(before.generation);
  // These leaf canaries do not own canonical private data. A route/root key
  // would erase unrelated local state instead of honouring each view's key.
  expect(settings.isConnected).toBe(true);
  expect(settings).not.toBeVisible();
  expect(settings).toHaveValue("unrelated local preference");
  expect(screen.getByLabelText("Learn inner draft")).toBe(learn);
  expect(learn).toHaveValue("independent learning draft");
  expect(events).toEqual(["open:Settings", "close:Settings", "open:Learn"]);
  act(() => { window.dispatchEvent(new Event("r43:work")); });
  expect(events.at(-1)).toBe("work:Learn");
  fireEvent.click(screen.getByRole("link", { name: "Settings app" }));
  expect(await screen.findByLabelText("Settings inner draft")).toBe(settings);
  expect(within(screen.getByRole("region", { name: "Settings app" })).getByLabelText("Layout name")).toBe(layout);
  expect(layout).toHaveValue("presentation layout");
  expect(settings).toHaveValue("unrelated local preference");
});

it("uses exclusive display utilities on the same retained app wrapper", async () => {
  render(<BrowserRouter><Link to="/learn">Learn app</Link><Link to="/settings">Settings app</Link><UnifiedAppsHost /></BrowserRouter>);
  const input = await screen.findByLabelText("Settings inner draft");
  const wrapper = screen.getByRole("region", { name: "Settings app" }).parentElement!;
  expect(wrapper).toHaveClass("flex");
  expect(wrapper).not.toHaveClass("hidden");
  expect(wrapper).not.toHaveAttribute("style");
  fireEvent.click(screen.getByRole("link", { name: "Learn app" }));
  await screen.findByLabelText("Learn inner draft");
  expect(wrapper.isConnected).toBe(true);
  expect(input.isConnected).toBe(true);
  expect.soft(wrapper).toHaveClass("hidden");
  expect.soft(wrapper).not.toHaveClass("flex");
  expect.soft(wrapper).not.toHaveAttribute("style");
  fireEvent.click(screen.getByRole("link", { name: "Settings app" }));
  expect(await screen.findByLabelText("Settings inner draft")).toBe(input);
  expect(screen.getByRole("region", { name: "Settings app" }).parentElement).toBe(wrapper);
  expect(wrapper).toHaveClass("flex");
  expect(wrapper).not.toHaveClass("hidden");
  expect(wrapper).not.toHaveAttribute("style");
});

it("closes the widget catalogue after a widget is added", async () => {
  window.history.replaceState(null, "", "/terminal");
  render(<QueryClientProvider client={client}><BrowserRouter><UnifiedAppsHost /></BrowserRouter></QueryClientProvider>);
  const app = await screen.findByRole("region", { name: "Terminal app" });
  // Overview exposes the Welcome and Positions leaves used by this journey.
  fireEvent.click(within(app).getByText("Layout actions"));
  fireEvent.change(within(app).getByRole("combobox", { name: "Terminal preset" }), { target: { value: "overview" } });
  fireEvent.click(within(app).getByText("Layout actions"));
  // A tab label is not proof that its real content rendered successfully.
  expect(await within(app).findByTestId("welcome-card")).toBeVisible();
  const existingPositions = await within(app).findByRole("region", { name: "Positions book" });
  fireEvent.click(within(app).getByRole("button", { name: "Add widget" }));
  expect(await screen.findByRole("dialog", { name: "Terminal widgets" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Add Positions" }));
  await vi.waitFor(() => {
    expect(screen.queryByRole("dialog", { name: "Terminal widgets" })).not.toBeInTheDocument();
  });
  expect(within(app).getAllByRole("tab", { name: "Positions" }).length).toBeGreaterThan(0);
  await vi.waitFor(() => expect(within(app).getAllByRole("region", { name: "Positions book" })).toHaveLength(2));
  const addedPositions = within(app).getAllByRole("region", { name: "Positions book" }).find(book => book !== existingPositions);
  expect(addedPositions).toBeVisible();
  expect(within(app).queryByText(/Something went wrong|Failed to load/)).not.toBeInTheDocument();
});

it("closes the widget catalogue when Enter adds the first search match", async () => {
  window.history.replaceState(null, "", "/terminal");
  render(<QueryClientProvider client={client}><BrowserRouter><UnifiedAppsHost /></BrowserRouter></QueryClientProvider>);
  const app = await screen.findByRole("region", { name: "Terminal app" });
  // The fresh default selects Watchlist; use the catalogue-backed Overview.
  fireEvent.click(within(app).getByText("Layout actions"));
  fireEvent.change(within(app).getByRole("combobox", { name: "Terminal preset" }), { target: { value: "overview" } });
  fireEvent.click(within(app).getByText("Layout actions"));
  // A tab label is not proof that its real content rendered successfully.
  expect(await within(app).findByTestId("welcome-card")).toBeVisible();
  fireEvent.click(within(app).getByRole("button", { name: "Add widget" }));
  const dialog = await screen.findByRole("dialog", { name: "Terminal widgets" });
  const search = within(dialog).getByRole("textbox", { name: "Search widgets" });
  fireEvent.change(search, { target: { value: "calculator" } });
  expect(fireEvent.keyDown(search, { key: "Enter" })).toBe(false);
  await vi.waitFor(() => {
    expect(screen.queryByRole("dialog", { name: "Terminal widgets" })).not.toBeInTheDocument();
  });
  expect(within(app).getAllByRole("tab", { name: "Calculator" }).length).toBeGreaterThan(0);
  const calculator = await within(app).findByRole("region", { name: "Trade calculator" });
  expect(calculator).toBeVisible();
  expect(within(calculator).getByLabelText("Account Capital")).toHaveValue(500000);
  expect(within(app).queryByText(/Something went wrong|Failed to load/)).not.toBeInTheDocument();
});
