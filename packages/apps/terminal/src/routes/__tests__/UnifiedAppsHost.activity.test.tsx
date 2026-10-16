import { useEffect, useState } from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { BrowserRouter, Link } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
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

beforeEach(() => {
  events.length = 0;
  localStorage.clear();
  window.history.replaceState(null, "", "/settings");
  const rect = { x: 0, y: 0, width: 1024, height: 700, top: 0, left: 0, right: 1024, bottom: 700, toJSON: () => ({}) };
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(rect);
  vi.stubGlobal("ResizeObserver", class {
    constructor(private callback: ResizeObserverCallback) {}
    observe(target: Element) { this.callback([{ target, contentRect: rect } as ResizeObserverEntry], this as unknown as ResizeObserver); }
    unobserve() {}
    disconnect() {}
  });
});
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("persists a restored model before any subsequent docking action or unmount", async () => {
  const named = buildAppPreset("settings", "default");
  named.layout.id = "named-layout-root";
  saveAppLayout("settings", "Named", named);
  render(<BrowserRouter><UnifiedAppsHost /></BrowserRouter>);
  await screen.findByLabelText("Settings inner draft");
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
  render(<BrowserRouter><UnifiedAppsHost /></BrowserRouter>);
  const app = await screen.findByRole("region", { name: "Terminal app" });
  fireEvent.click(within(app).getByRole("button", { name: "Add widget" }));
  expect(await screen.findByRole("dialog", { name: "Terminal widgets" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Add Positions" }));
  await vi.waitFor(() => {
    expect(screen.queryByRole("dialog", { name: "Terminal widgets" })).not.toBeInTheDocument();
  });
  expect(within(app).getAllByRole("tab", { name: "Positions" }).length).toBeGreaterThan(0);
});
