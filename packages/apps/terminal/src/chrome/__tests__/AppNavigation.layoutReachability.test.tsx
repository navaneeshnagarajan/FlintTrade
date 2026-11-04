import { useState } from "react";
import { act, cleanup, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import userEvent from "@testing-library/user-event";
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
// jsdom has no canvas rendering context. Keep the real panel/factory and make
// only the expensive chart leaf inert, as with the Settings/Learn canaries.
vi.mock("@/widgets/analysis/Chart/ChartWidget", () => ({ default: () => <p>Chart leaf</p> }));
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
function renderShell(path = "/settings") {
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><AppLayout /></MemoryRouter></QueryClientProvider>);
}

describe("compact app navigation and layout ownership", () => {
  it("groups every app exactly once in the header switcher and focuses the newly selected app", async () => {
    renderShell();
    await screen.findByLabelText("Settings navigation canary");
    const nav = screen.getByRole("navigation", { name: "Apps" });
    const choose = within(nav).getByRole("button", { name: "Choose app" });
    expect(choose).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(choose);
    for (const [group, names] of [
      ["Trading", ["Terminal", "Portfolio", "Brokers"]],
      ["Studio", ["Testing", "Automation", "Learn"]],
      ["Review", ["Reports", "System"]],
      ["Utilities", ["Settings"]],
    ] as const) {
      expect(within(within(nav).getByRole("list", { name: group })).getAllByRole("link").map(link => link.textContent)).toEqual(names);
    }
    expect(within(nav).getAllByRole("link").map(link => [link.textContent, link.getAttribute("href")]).sort()).toEqual([...expectedApps].sort());
    expect(within(screen.getByRole("banner")).getByRole("navigation", { name: "Apps" })).toBe(nav);
    for (const link of within(nav).getAllByRole("link")) expect(link).toBeVisible();
    expect(within(nav).getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
    fireEvent.click(within(nav).getByRole("link", { name: "Learn" }));
    await screen.findByLabelText("Learn navigation canary");
    expect(screen.getByRole("main", { name: "Learn" })).toHaveFocus();
    expect(choose).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(choose);
    expect(within(nav).getByRole("link", { name: "Learn" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Settings" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("main", { name: "Learn" })).toHaveFocus();
    expect(screen.queryByTestId("nav-drawer-btn")).not.toBeInTheDocument();
  });

  it("opens compact navigation by keyboard, returns focus on Escape, and hands route focus to main", async () => {
    vi.spyOn(window, "matchMedia").mockImplementation(query => ({
      matches: query === "(max-width: 767px)", media: query, onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: () => false,
    }));
    const user = userEvent.setup();
    renderShell();
    await screen.findByLabelText("Settings navigation canary");
    const nav = within(screen.getByRole("navigation", { name: "Apps" }));
    const choose = nav.getByRole("button", { name: "Choose app" });
    expect(choose).toHaveAttribute("aria-expanded", "false");
    expect(nav.getAllByRole("link")).toHaveLength(1);
    expect(choose).toHaveAttribute("data-slot", "button");
    expect(document.getElementById(choose.getAttribute("aria-controls")!)).not.toBeVisible();
    expect(nav.getByRole("link", { name: "Settings" })).toBeVisible();
    choose.focus();
    await user.keyboard("{Enter}");
    expect(choose).toHaveAttribute("aria-expanded", "true");
    expect(nav.getAllByRole("link")).toHaveLength(9);
    await user.tab();
    expect(nav.getByRole("link", { name: "Terminal" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(choose).toHaveFocus();
    expect(choose).toHaveAttribute("aria-expanded", "false");
    await user.keyboard("{Enter}");
    await user.click(nav.getByRole("link", { name: "Learn" }));
    await screen.findByLabelText("Learn navigation canary");
    expect(screen.getByRole("main", { name: "Learn" })).toHaveFocus();
    expect(choose).toHaveAttribute("aria-expanded", "false");
    expect(choose).toHaveTextContent("Learn");
    choose.focus();
    await user.keyboard(" ");
    expect(choose).toHaveAttribute("aria-expanded", "true");
    await user.click(nav.getByRole("link", { name: "Learn" }));
    expect(choose).toHaveFocus();
    expect(choose).toHaveAttribute("aria-expanded", "false");
    expect(useBrokerStore.getState().activeAccountId).toBeNull();
    expect(useModeStore.getState().mode).toBe("explore");
  });

  it("keeps keyboard focus on a visible navigation control across compact breakpoint changes", async () => {
    const changes = new EventTarget();
    const media = {
      matches: false, media: "(max-width: 767px)", onchange: null,
      addEventListener: changes.addEventListener.bind(changes),
      removeEventListener: changes.removeEventListener.bind(changes),
      dispatchEvent: changes.dispatchEvent.bind(changes),
      addListener: vi.fn(), removeListener: vi.fn(),
    };
    const original = window.matchMedia;
    vi.spyOn(window, "matchMedia").mockImplementation(query => query === media.media ? media : original(query));
    renderShell();
    const draft = await screen.findByLabelText("Settings navigation canary");
    const nav = within(screen.getByRole("navigation", { name: "Apps" }));
    fireEvent.click(nav.getByRole("button", { name: "Choose app" }));
    nav.getByRole("link", { name: "Learn" }).focus();
    act(() => { media.matches = true; media.dispatchEvent(new Event("change")); });
    const choose = nav.getByRole("button", { name: "Choose app" });
    expect(choose).toHaveFocus();
    expect(choose).toHaveAttribute("aria-expanded", "false");
    act(() => { media.matches = false; media.dispatchEvent(new Event("change")); });
    expect(choose).toHaveFocus();
    expect(choose).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(choose);
    expect(nav.getAllByRole("link")).toHaveLength(9);
    expect(screen.getByLabelText("Settings navigation canary")).toBe(draft);
  });

  it("reaches real compact layout controls and saves, resets and restores a named composition", async () => {
    renderShell();
    await screen.findByLabelText("Settings navigation canary");
    const app = within(screen.getByRole("region", { name: "Settings app" }));
    const chrome = within(screen.getByLabelText("Settings layout controls"));
    expect(chrome.getByRole("combobox", { name: "Compact panel" })).toBeEnabled();
    expect(chrome.getByLabelText("Layout name")).not.toBeVisible();
    fireEvent.click(chrome.getByText("Layout actions"));
    expect(chrome.getByRole("textbox", { name: "Layout name" })).toBeVisible();
    expect(chrome.getByRole("combobox", { name: "Settings preset" })).toBeEnabled();
    fireEvent.click(chrome.getByRole("button", { name: "Add widget" }));
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Settings widgets");
    fireEvent.click(screen.getByRole("button", { name: "Add Shared knowledge" }));
    await screen.findByText("Knowledge leaf");
    fireEvent.change(chrome.getByRole("textbox", { name: "Layout name" }), { target: { value: "Compact saved" } });
    fireEvent.click(chrome.getByRole("button", { name: "Save layout" }));
    expect(app.getByRole("status")).toHaveTextContent("Saved Compact saved");
    const saved = readAppLayouts("settings")["Compact saved"];
    expect(JSON.stringify(saved)).toContain('"component":"knowledge-library"');
    expect(chrome.getByRole("button", { name: "Export layout" })).toBeVisible();
    expect(chrome.getByLabelText("Import app layout")).toBeVisible();
    const preset = chrome.getByRole("combobox", { name: "Settings preset" });
    await userEvent.setup().selectOptions(preset, "default");
    expect(preset).toHaveValue("");
    expect(app.getByRole("status")).toHaveTextContent("Applied Preferences preset");
    expect(screen.queryByText("Knowledge leaf")).not.toBeInTheDocument();
    fireEvent.change(chrome.getByRole("combobox", { name: "Restore saved layout" }), { target: { value: "Compact saved" } });
    expect(await screen.findByText("Knowledge leaf")).toBeInTheDocument();
    expect(preset).toHaveValue("");
    expect(app.getByRole("status")).toHaveTextContent("Restored Compact saved");
    // A preset is an action, not an inferred identity for a customised layout.
    // Choosing the same preset again must still replace that composition.
    await userEvent.setup().selectOptions(preset, "default");
    expect(screen.queryByText("Knowledge leaf")).not.toBeInTheDocument();
    expect(preset).toHaveValue("");
    fireEvent.change(chrome.getByRole("textbox", { name: "Layout name" }), { target: { value: "Default saved" } });
    fireEvent.click(chrome.getByRole("button", { name: "Save layout" }));
    expect(app.getByRole("status")).toHaveTextContent("Saved Default saved");
    fireEvent.click(chrome.getByRole("button", { name: "Reset app layout" }));
    expect(app.getByRole("status")).toHaveTextContent("Reset app layout");
    expect(preset).toHaveValue("");
    expect(chrome.getByText("1 panels")).toBeVisible();
    expect(chrome.getByRole("combobox", { name: "Compact panel" })).toHaveTextContent("Preferences");
    expect(screen.queryByText("Knowledge leaf")).not.toBeInTheDocument();
    fireEvent.change(chrome.getByRole("combobox", { name: "Restore saved layout" }), { target: { value: "Compact saved" } });
    expect(app.getByRole("status")).toHaveTextContent("Restored Compact saved");
    expect(preset).toHaveValue("");
    expect(readAppLayouts("settings")["Compact saved"]).toEqual(saved);
    expect(await screen.findByText("Knowledge leaf")).toBeInTheDocument();
    expect(useAuthStore.getState().status).toBe("logged-out");
    expect(useBrokerStore.getState().activeAccountId).toBeNull();
    expect(useModeStore.getState().mode).toBe("explore");
  });

  it("exports the rendered composition and imports it after a preset change without changing execution scope", async () => {
    // Only the browser download/file boundary is intercepted. The composition,
    // serialisation, validation and mounted import owner are the real ones.
    const createObjectURL = vi.fn<(blob: Blob) => string>(() => "blob:layout-download");
    const revokeObjectURL = vi.fn();
    class DownloadURL extends URL {}
    Object.defineProperties(DownloadURL, {
      createObjectURL: { value: createObjectURL }, revokeObjectURL: { value: revokeObjectURL },
    });
    vi.stubGlobal("URL", DownloadURL);
    const downloads: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { downloads.push(this.download); });
    const readBlob = (blob: Blob) => new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => typeof reader.result === "string" ? resolve(reader.result) : reject(new Error("Expected layout text"));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(blob);
    });
    const user = userEvent.setup();
    renderShell();
    await screen.findByLabelText("Settings navigation canary");
    const app = within(screen.getByRole("region", { name: "Settings app" }));
    const chrome = within(screen.getByLabelText("Settings layout controls"));
    await user.click(chrome.getByRole("button", { name: "Add widget" }));
    await user.click(screen.getByRole("button", { name: "Add Shared knowledge" }));
    expect(await screen.findByText("Knowledge leaf")).toBeVisible();
    const disclosure = chrome.getByText("Layout actions").closest("summary")!;
    disclosure.focus();
    await user.keyboard("{Enter}");
    await user.click(chrome.getByRole("button", { name: "Save layout" }));
    expect(app.getByRole("alert")).toHaveTextContent("Choose a valid layout name.");
    await user.click(chrome.getByRole("button", { name: "Export layout" }));
    expect(downloads).toEqual(["flinttrade-settings-layout.json"]);
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:layout-download");
    const exported = createObjectURL.mock.calls[0][0];
    const envelope = JSON.parse(await readBlob(exported));
    expect(envelope).toMatchObject({ version: 1, app: "settings" });
    expect(JSON.stringify(envelope)).toContain('"component":"knowledge-library"');
    await user.selectOptions(chrome.getByRole("combobox", { name: "Settings preset" }), "default");
    expect(screen.queryByText("Knowledge leaf")).not.toBeInTheDocument();
    const file = new File([exported], "layout.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: () => readBlob(file) });
    await user.upload(chrome.getByLabelText("Import app layout"), file);
    expect(await screen.findByText("Knowledge leaf")).toBeVisible();
    expect(app.getByRole("status")).toHaveTextContent("Imported presentation layout; execution unchanged.");
    expect(chrome.getByRole("combobox", { name: "Settings preset" })).toHaveValue("");
    expect(app.queryByRole("alert")).not.toBeInTheDocument();
    expect(app.getByTestId("app-execution-scope")).toHaveTextContent("Example · No execution account selected");
    expect(useBrokerStore.getState().activeAccountId).toBeNull();
    expect(useModeStore.getState().mode).toBe("explore");
  });

  it("keeps incompatible layout import errors visible without replacing mounted drafts or scope", async () => {
    renderShell();
    const draft = await screen.findByLabelText("Settings navigation canary");
    fireEvent.change(draft, { target: { value: "Keep this local draft" } });
    const app = within(screen.getByRole("region", { name: "Settings app" }));
    const chrome = within(screen.getByLabelText("Settings layout controls"));
    fireEvent.click(chrome.getByText("Layout actions"));
    fireEvent.change(chrome.getByRole("textbox", { name: "Layout name" }), { target: { value: "Before import" } });
    fireEvent.click(chrome.getByRole("button", { name: "Save layout" }));
    expect(app.getByRole("status")).toHaveTextContent("Saved Before import");
    const document = JSON.stringify({ version: 1, app: "terminal", layout: {} });
    const file = new File([document], "wrong-app.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: async () => document });
    await userEvent.setup().upload(chrome.getByLabelText("Import app layout"), file);
    expect(await app.findByRole("alert")).toHaveTextContent("Not a compatible fresh app layout. Authority and legacy layouts cannot be imported.");
    expect(screen.getByLabelText("Settings navigation canary")).toBe(draft);
    expect(draft).toHaveValue("Keep this local draft");
    expect(app.queryByRole("status")).not.toBeInTheDocument();
    // A later successful action must retire the refusal, not leave both shown.
    fireEvent.click(chrome.getByRole("button", { name: "Save layout" }));
    expect(app.getByRole("status")).toHaveTextContent("Saved Before import");
    expect(app.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.change(chrome.getByRole("textbox", { name: "Layout name" }), { target: { value: "" } });
    fireEvent.click(chrome.getByRole("button", { name: "Save layout" }));
    expect(app.getByRole("alert")).toHaveTextContent("Choose a valid layout name.");
    expect(app.queryByRole("status")).not.toBeInTheDocument();
    fireEvent.change(chrome.getByRole("combobox", { name: "Restore saved layout" }), { target: { value: "Before import" } });
    expect(app.getByRole("status")).toHaveTextContent("Restored Before import");
    expect(app.queryByRole("alert")).not.toBeInTheDocument();
    expect(useBrokerStore.getState().activeAccountId).toBeNull();
    expect(useModeStore.getState().mode).toBe("explore");
  });

  it("keeps the skip target focusable and removes navigation and retained app data when locked", async () => {
    renderShell();
    const draft = await screen.findByLabelText("Settings navigation canary");
    const main = screen.getByRole("main", { name: "Settings" });
    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute("href", `#${main.id}`);
    main.focus();
    expect(main).toHaveFocus();
    act(() => { useAuthStore.setState({ status: "pin-required" }); });
    expect(screen.queryByRole("navigation", { name: "Apps" })).not.toBeInTheDocument();
    expect(screen.queryByRole("main")).not.toBeInTheDocument();
    expect(draft.isConnected).toBe(false);
  });

  it("reports the real Terminal composition after preset, reset, restore and repeated public preset commands", async () => {
    const user = userEvent.setup();
    renderShell("/terminal");
    const app = within(await screen.findByRole("region", { name: "Terminal app" }));
    const chrome = within(screen.getByLabelText("Terminal layout controls"));
    await user.click(chrome.getByText("Layout actions"));
    await user.click(chrome.getByRole("button", { name: "Reset app layout" }));
    const preset = chrome.getByRole("combobox", { name: "Terminal preset" });
    const panelNames = () => within(chrome.getByRole("combobox", { name: "Compact panel" })).getAllByRole("option").map(option => option.textContent);
    expect(chrome.getByText("5 panels")).toBeVisible();
    expect(panelNames()).toContain("Welcome overview");
    await user.type(chrome.getByRole("textbox", { name: "Layout name" }), "Default panels");
    await user.click(chrome.getByRole("button", { name: "Save layout" }));
    await user.selectOptions(preset, "market-watch");
    expect(chrome.getByText("4 panels")).toBeVisible();
    expect(panelNames()).not.toContain("Welcome overview");
    expect(panelNames()).toContain("Watchlist");
    expect(preset).toHaveValue("");
    expect(app.getByRole("status")).toHaveTextContent("Applied Market watch (FlintTrade) preset");
    await user.click(chrome.getByRole("button", { name: "Reset app layout" }));
    expect(chrome.getByText("5 panels")).toBeVisible();
    expect(panelNames()).toContain("Welcome overview");
    expect(preset).toHaveValue("");
    expect(app.getByRole("status")).toHaveTextContent("Reset app layout");
    for (let attempt = 0; attempt < 2; attempt += 1) {
      act(() => { window.dispatchEvent(new CustomEvent("flinttrade:apply-layout", { detail: { presetId: "market-watch" } })); });
      expect(chrome.getByText("4 panels")).toBeVisible();
      expect(preset).toHaveValue("");
      expect(app.getByRole("status")).toHaveTextContent("Applied Market watch (FlintTrade) preset");
      await user.selectOptions(chrome.getByRole("combobox", { name: "Restore saved layout" }), "Default panels");
      expect(chrome.getByText("5 panels")).toBeVisible();
      expect(panelNames()).toContain("Welcome overview");
      expect(preset).toHaveValue("");
      expect(app.getByRole("status")).toHaveTextContent("Restored Default panels");
    }
    expect(useBrokerStore.getState().activeAccountId).toBeNull();
    expect(useModeStore.getState().mode).toBe("explore");
  });

  it.each(["header", "custom", "event", "route"])("starts fresh %s widget entry from an empty presentation, not a hidden default", async (entry: string) => {
    if (entry === "route") {
      render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[{ pathname: "/terminal", state: { openWidget: { widgetId: "chart" } } }]}><AppLayout /></MemoryRouter></QueryClientProvider>);
    } else {
      renderShell("/terminal");
      const chooser = await screen.findByRole("region", { name: "Choose a layout" });
      const chrome = within(screen.getByLabelText("Terminal layout controls"));
      expect(chrome.getByText("No layout selected")).toBeVisible();
      expect(chrome.queryByText("5 panels")).not.toBeInTheDocument();
      expect(chrome.queryByRole("combobox", { name: "Compact panel" })).not.toBeInTheDocument();
      expect(screen.queryByText("Chart leaf")).not.toBeInTheDocument();
      expect(readAppLayouts("terminal").Current).toBeUndefined();
      if (entry === "event") {
        act(() => window.dispatchEvent(new CustomEvent("flinttrade:app-widget", { detail: { widgetId: "chart" } })));
      } else {
        fireEvent.click(entry === "header" ? chrome.getByRole("button", { name: "Add widget" }) : within(chooser).getByRole("button", { name: "Create new layout" }));
        fireEvent.click(await screen.findByRole("button", { name: "Add Chart" }));
      }
    }
    expect(await screen.findByText("Chart leaf")).toBeVisible();
    expect(screen.queryByRole("region", { name: "Choose a layout" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Terminal layout controls")).toHaveTextContent("1 panels");
    const json = JSON.stringify(readAppLayouts("terminal").Current);
    expect(json.match(/"component":"chart"/g)).toHaveLength(1);
    expect(json).not.toContain('"component":"watchlist"');
    expect(useBrokerStore.getState().activeAccountId).toBeNull();
    expect(useModeStore.getState().mode).toBe("explore");
  });

  it("shows templates only for a fresh Terminal and persists the selected canonical composition", async () => {
    const view = renderShell("/terminal");
    const chooser = await screen.findByRole("region", { name: "Choose a layout" });
    expect(readAppLayouts("terminal").Current).toBeUndefined();
    fireEvent.click(within(chooser).getByRole("button", { name: "Use Watchlist driven layout" }));
    expect(screen.queryByRole("region", { name: "Choose a layout" })).not.toBeInTheDocument();
    const current = readAppLayouts("terminal").Current;
    expect(JSON.stringify(current)).toContain('"component":"watchlist"');
    expect(JSON.stringify(current)).not.toContain('"overview:WelcomeCard"');
    view.unmount();
    renderShell("/terminal");
    await screen.findByRole("region", { name: "Terminal app" });
    expect(screen.queryByRole("region", { name: "Choose a layout" })).not.toBeInTheDocument();
    expect(readAppLayouts("terminal").Current).toEqual(current);
    expect(useBrokerStore.getState().activeAccountId).toBeNull();
    expect(useModeStore.getState().mode).toBe("explore");
  });

  it("retains the exact portalled layout draft and import input across app navigation", async () => {
    renderShell();
    await screen.findByLabelText("Settings navigation canary");
    const chrome = screen.getByLabelText("Settings layout controls");
    expect(screen.getByRole("banner")).toContainElement(chrome);
    fireEvent.click(within(chrome).getByText("Layout actions"));
    const draft = within(chrome).getByLabelText("Layout name");
    const file = within(chrome).getByLabelText("Import app layout");
    fireEvent.change(draft, { target: { value: "Unsaved chrome draft" } });
    const nav = within(screen.getByRole("navigation", { name: "Apps" }));
    fireEvent.click(nav.getByRole("button", { name: "Choose app" }));
    fireEvent.click(nav.getByRole("link", { name: "Learn" }));
    await screen.findByLabelText("Learn navigation canary");
    expect(chrome.isConnected).toBe(true);
    expect(chrome).not.toBeVisible();
    expect(screen.getAllByRole("button", { name: "Add widget" })).toHaveLength(1);
    fireEvent.click(nav.getByRole("link", { name: "Settings" }));
    await screen.findByLabelText("Settings navigation canary");
    expect(screen.getByLabelText("Settings layout controls")).toBe(chrome);
    expect(within(chrome).getByLabelText("Layout name")).toBe(draft);
    expect(within(chrome).getByLabelText("Import app layout")).toBe(file);
    expect(draft).toHaveValue("Unsaved chrome draft");
    expect(readAppLayouts("settings")["Unsaved chrome draft"]).toBeUndefined();
    expect(useBrokerStore.getState().activeAccountId).toBeNull();
    expect(useModeStore.getState().mode).toBe("explore");
  });

  it("routes a public reset command only to the active toolbar owner", async () => {
    renderShell();
    await screen.findByLabelText("Settings navigation canary");
    const nav = within(screen.getByRole("navigation", { name: "Apps" }));
    fireEvent.click(nav.getByRole("button", { name: "Choose app" }));
    fireEvent.click(nav.getByRole("link", { name: "Learn" }));
    const draft = await screen.findByLabelText("Learn navigation canary");
    fireEvent.change(draft, { target: { value: "Retained hidden learning draft" } });
    fireEvent.click(nav.getByRole("link", { name: "Settings" }));
    await screen.findByLabelText("Settings navigation canary");
    fireEvent.click(screen.getByRole("button", { name: "Add widget" }));
    fireEvent.click(screen.getByRole("button", { name: "Add Shared knowledge" }));
    await screen.findByText("Knowledge leaf");
    const { result } = renderHook(() => useCommandRegistry());
    fireEvent.click(within(screen.getByLabelText("Settings layout controls")).getByText("Layout actions"));
    fireEvent.change(screen.getByRole("textbox", { name: "Layout name" }), { target: { value: "Before command" } });
    fireEvent.click(screen.getByRole("button", { name: "Save layout" }));
    expect(screen.getByRole("status")).toHaveTextContent("Saved Before command");
    act(() => { window.dispatchEvent(new CustomEvent("flinttrade:apply-layout", { detail: { presetId: "not-a-compatible-preset" } })); });
    expect(screen.getByRole("alert")).toHaveTextContent("This preset is not compatible with the current app.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText("Knowledge leaf")).toBeVisible();
    const reset = result.current.commands.find(command => command.id === "action:reset-layout");
    expect(reset).toBeDefined();
    act(() => { reset!.action(); });
    expect(screen.queryByText("Knowledge leaf")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Reset app layout");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Settings preset" })).toHaveValue("");
    expect(draft.isConnected).toBe(true);
    expect(draft).not.toBeVisible();
    fireEvent.click(nav.getByRole("button", { name: "Choose app" }));
    fireEvent.click(nav.getByRole("link", { name: "Learn" }));
    expect(await screen.findByLabelText("Learn navigation canary")).toBe(draft);
    expect(draft).toHaveValue("Retained hidden learning draft");
  });
});
