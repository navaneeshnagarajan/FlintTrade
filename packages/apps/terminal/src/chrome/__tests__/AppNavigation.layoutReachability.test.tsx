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
  it("groups every app exactly once beside the content and focuses the newly selected app", async () => {
    renderShell();
    await screen.findByLabelText("Settings navigation canary");
    const nav = screen.getByRole("navigation", { name: "Apps" });
    for (const [group, names] of [
      ["Trading", ["Terminal", "Portfolio", "Brokers"]],
      ["Studio", ["Testing", "Automation", "Learn"]],
      ["Review", ["Reports", "System"]],
      ["Utilities", ["Settings"]],
    ] as const) {
      expect(within(within(nav).getByRole("list", { name: group })).getAllByRole("link").map(link => link.textContent)).toEqual(names);
    }
    expect(within(nav).getAllByRole("link").map(link => [link.textContent, link.getAttribute("href")]).sort()).toEqual([...expectedApps].sort());
    expect(within(screen.getByRole("banner")).queryByRole("navigation", { name: "Apps" })).not.toBeInTheDocument();
    for (const link of within(nav).getAllByRole("link")) expect(link).toBeVisible();
    expect(within(nav).getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
    fireEvent.click(within(nav).getByRole("link", { name: "Learn" }));
    await screen.findByLabelText("Learn navigation canary");
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
    nav.getByRole("link", { name: "Learn" }).focus();
    act(() => { media.matches = true; media.dispatchEvent(new Event("change")); });
    const choose = nav.getByRole("button", { name: "Choose app" });
    expect(choose).toHaveFocus();
    expect(choose).toHaveAttribute("aria-expanded", "false");
    act(() => { media.matches = false; media.dispatchEvent(new Event("change")); });
    expect(nav.getByRole("link", { name: "Settings" })).toHaveFocus();
    expect(nav.getAllByRole("link")).toHaveLength(9);
    expect(screen.getByLabelText("Settings navigation canary")).toBe(draft);
  });

  it("reaches real compact layout controls and saves, resets and restores a named composition", async () => {
    renderShell();
    await screen.findByLabelText("Settings navigation canary");
    const app = within(screen.getByRole("region", { name: "Settings app" }));
    expect(app.getByRole("combobox", { name: "Settings preset" })).toBeEnabled();
    expect(app.getByRole("combobox", { name: "Compact panel" })).toBeEnabled();
    expect(app.getByLabelText("Layout name")).not.toBeVisible();
    fireEvent.click(app.getByText("Layout actions"));
    expect(app.getByRole("textbox", { name: "Layout name" })).toBeVisible();
    fireEvent.click(app.getByRole("button", { name: "Add widget" }));
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Settings widgets");
    fireEvent.click(screen.getByRole("button", { name: "Add Shared knowledge" }));
    await screen.findByText("Knowledge leaf");
    fireEvent.change(app.getByRole("textbox", { name: "Layout name" }), { target: { value: "Compact saved" } });
    fireEvent.click(app.getByRole("button", { name: "Save layout" }));
    expect(app.getByRole("status")).toHaveTextContent("Saved Compact saved");
    const saved = readAppLayouts("settings")["Compact saved"];
    expect(JSON.stringify(saved)).toContain('"component":"knowledge-library"');
    expect(app.getByRole("button", { name: "Export layout" })).toBeVisible();
    expect(app.getByLabelText("Import app layout")).toBeVisible();
    const preset = app.getByRole("combobox", { name: "Settings preset" });
    await userEvent.setup().selectOptions(preset, "default");
    expect(preset).toHaveValue("");
    expect(app.getByRole("status")).toHaveTextContent("Applied Preferences preset");
    expect(screen.queryByText("Knowledge leaf")).not.toBeInTheDocument();
    fireEvent.change(app.getByRole("combobox", { name: "Restore saved layout" }), { target: { value: "Compact saved" } });
    expect(await screen.findByText("Knowledge leaf")).toBeInTheDocument();
    expect(preset).toHaveValue("");
    expect(app.getByRole("status")).toHaveTextContent("Restored Compact saved");
    // A preset is an action, not an inferred identity for a customised layout.
    // Choosing the same preset again must still replace that composition.
    await userEvent.setup().selectOptions(preset, "default");
    expect(screen.queryByText("Knowledge leaf")).not.toBeInTheDocument();
    expect(preset).toHaveValue("");
    fireEvent.change(app.getByRole("textbox", { name: "Layout name" }), { target: { value: "Default saved" } });
    fireEvent.click(app.getByRole("button", { name: "Save layout" }));
    expect(app.getByRole("status")).toHaveTextContent("Saved Default saved");
    fireEvent.click(app.getByRole("button", { name: "Reset app layout" }));
    expect(app.getByRole("status")).toHaveTextContent("Reset app layout");
    expect(preset).toHaveValue("");
    expect(app.getByText("1 panels")).toBeVisible();
    expect(app.getByRole("combobox", { name: "Compact panel" })).toHaveTextContent("Preferences");
    expect(screen.queryByText("Knowledge leaf")).not.toBeInTheDocument();
    fireEvent.change(app.getByRole("combobox", { name: "Restore saved layout" }), { target: { value: "Compact saved" } });
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
    await user.click(app.getByRole("button", { name: "Add widget" }));
    await user.click(screen.getByRole("button", { name: "Add Shared knowledge" }));
    expect(await screen.findByText("Knowledge leaf")).toBeVisible();
    const disclosure = app.getByText("Layout actions").closest("summary")!;
    disclosure.focus();
    await user.keyboard("{Enter}");
    await user.click(app.getByRole("button", { name: "Save layout" }));
    expect(app.getByRole("alert")).toHaveTextContent("Choose a valid layout name.");
    await user.click(app.getByRole("button", { name: "Export layout" }));
    expect(downloads).toEqual(["flinttrade-settings-layout.json"]);
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:layout-download");
    const exported = createObjectURL.mock.calls[0][0];
    const envelope = JSON.parse(await readBlob(exported));
    expect(envelope).toMatchObject({ version: 1, app: "settings" });
    expect(JSON.stringify(envelope)).toContain('"component":"knowledge-library"');
    await user.selectOptions(app.getByRole("combobox", { name: "Settings preset" }), "default");
    expect(screen.queryByText("Knowledge leaf")).not.toBeInTheDocument();
    const file = new File([exported], "layout.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: () => readBlob(file) });
    await user.upload(app.getByLabelText("Import app layout"), file);
    expect(await screen.findByText("Knowledge leaf")).toBeVisible();
    expect(app.getByRole("status")).toHaveTextContent("Imported presentation layout; execution unchanged.");
    expect(app.getByRole("combobox", { name: "Settings preset" })).toHaveValue("");
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
    fireEvent.click(app.getByText("Layout actions"));
    fireEvent.change(app.getByRole("textbox", { name: "Layout name" }), { target: { value: "Before import" } });
    fireEvent.click(app.getByRole("button", { name: "Save layout" }));
    expect(app.getByRole("status")).toHaveTextContent("Saved Before import");
    const document = JSON.stringify({ version: 1, app: "terminal", layout: {} });
    const file = new File([document], "wrong-app.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: async () => document });
    await userEvent.setup().upload(app.getByLabelText("Import app layout"), file);
    expect(await app.findByRole("alert")).toHaveTextContent("Not a compatible fresh app layout. Authority and legacy layouts cannot be imported.");
    expect(screen.getByLabelText("Settings navigation canary")).toBe(draft);
    expect(draft).toHaveValue("Keep this local draft");
    expect(app.queryByRole("status")).not.toBeInTheDocument();
    // A later successful action must retire the refusal, not leave both shown.
    fireEvent.click(app.getByRole("button", { name: "Save layout" }));
    expect(app.getByRole("status")).toHaveTextContent("Saved Before import");
    expect(app.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.change(app.getByRole("textbox", { name: "Layout name" }), { target: { value: "" } });
    fireEvent.click(app.getByRole("button", { name: "Save layout" }));
    expect(app.getByRole("alert")).toHaveTextContent("Choose a valid layout name.");
    expect(app.queryByRole("status")).not.toBeInTheDocument();
    fireEvent.change(app.getByRole("combobox", { name: "Restore saved layout" }), { target: { value: "Before import" } });
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
    const preset = app.getByRole("combobox", { name: "Terminal preset" });
    const panelNames = () => within(app.getByRole("combobox", { name: "Compact panel" })).getAllByRole("option").map(option => option.textContent);
    expect(app.getByText("5 panels")).toBeVisible();
    expect(panelNames()).toContain("Welcome overview");
    await user.click(app.getByText("Layout actions"));
    await user.type(app.getByRole("textbox", { name: "Layout name" }), "Default panels");
    await user.click(app.getByRole("button", { name: "Save layout" }));
    await user.selectOptions(preset, "market-watch");
    expect(app.getByText("4 panels")).toBeVisible();
    expect(panelNames()).not.toContain("Welcome overview");
    expect(panelNames()).toContain("Watchlist");
    expect(preset).toHaveValue("");
    expect(app.getByRole("status")).toHaveTextContent("Applied Market watch preset");
    await user.click(app.getByRole("button", { name: "Reset app layout" }));
    expect(app.getByText("5 panels")).toBeVisible();
    expect(panelNames()).toContain("Welcome overview");
    expect(preset).toHaveValue("");
    expect(app.getByRole("status")).toHaveTextContent("Reset app layout");
    for (let attempt = 0; attempt < 2; attempt += 1) {
      act(() => { window.dispatchEvent(new CustomEvent("flinttrade:apply-layout", { detail: { presetId: "market-watch" } })); });
      expect(app.getByText("4 panels")).toBeVisible();
      expect(preset).toHaveValue("");
      expect(app.getByRole("status")).toHaveTextContent("Applied Market watch preset");
      await user.selectOptions(app.getByRole("combobox", { name: "Restore saved layout" }), "Default panels");
      expect(app.getByText("5 panels")).toBeVisible();
      expect(panelNames()).toContain("Welcome overview");
      expect(preset).toHaveValue("");
      expect(app.getByRole("status")).toHaveTextContent("Restored Default panels");
    }
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
    fireEvent.click(within(screen.getByRole("region", { name: "Settings app" })).getByText("Layout actions"));
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
    fireEvent.click(nav.getByRole("link", { name: "Learn" }));
    expect(await screen.findByLabelText("Learn navigation canary")).toBe(draft);
    expect(draft).toHaveValue("Retained hidden learning draft");
  });
});
