import { Profiler } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { UnifiedAppsHost } from "../UnifiedAppsHost";
import SettingsRoute from "../SettingsRoute";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { captureOperatorIncidentScope } from "@/lib/operatorIncidentScope";
import { CanonicalDataClient } from "@/services/canonicalData";

// Keep the actual app Activity owner, router, docking renderer, Settings,
// DataSection and canonical hooks/client/decoder/stores. Unrelated widget
// contents are inert; geometry is supplied because jsdom has no layout engine.
vi.mock("@/layout/appWidgetFactory", () => ({ appWidgetFactory: (_app: string, node: { getComponent(): string }) => node.getComponent() === "preferences" ? <SettingsRoute /> : <p>Other app</p> }));
vi.mock("@/routes/TerminalRoute", () => ({ KillSwitchPill: () => null }));
vi.mock("@/chrome/InstrumentLinks", () => ({ InstrumentLinks: () => null }));
vi.mock("@/components/layout/CinematicLayout", () => ({ CinematicLayout: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("@/routes/SetupAccountRoute", () => ({ PracticeLaterSetup: () => null }));
vi.mock("@/tools/Settings/WatchlistManagerPanel", () => ({ WatchlistManagerPanel: () => null }));
vi.mock("@/tools/Settings/GeneralSection", () => ({ GeneralSection: () => <p>General settings</p> }));
vi.mock("@/hooks/useSettingsState", () => ({ useSettingsState: () => ({ general: {}, dataPaths: { fastStoragePath: "", archiveStoragePath: "" } }) }));

const base = "/ft-api/api/v1/data";
const serverScope = { principal_id: "synthetic", environment: "local_history", account_id: null, run_id: null, generation: 1 };
const catalogue = { scope: serverScope, datasets: [], legacy_history: "unqualified_legacy", portfolio: "Explicit records only" };
let queryClient: QueryClient;
let failures: unknown[];
let clients: CanonicalDataClient[];
let checkpoints: unknown[];
let commits: unknown[];
let retainedNode: HTMLElement | null;
let fiberIds: WeakMap<object, number>;
let nextFiberId: number;
interface Fiber { type: unknown; return: Fiber | null; alternate: Fiber | null }
function lineage(element: Element | null) {
  const key = element && Object.keys(element).find(name => name.startsWith("__reactFiber$"));
  let fiber = key ? (element as unknown as Record<string, Fiber>)[key] : null;
  const result: { component: string; instance: number }[] = [];
  while (fiber) {
    if (typeof fiber.type === "function" && ["SettingsRoute", "DataSection", "CanonicalDataControls", "DataSession", "DataView"].includes(fiber.type.name)) {
      let id = fiberIds.get(fiber) ?? (fiber.alternate ? fiberIds.get(fiber.alternate) : undefined);
      if (id === undefined) id = ++nextFiberId;
      fiberIds.set(fiber, id);
      result.push({ component: fiber.type.name, instance: id });
    }
    fiber = fiber.return;
  }
  return result;
}
function section() { return document.querySelector('[aria-label="Settings"] [role="tabpanel"]')?.id ?? null; }
function observe() {
  const node = document.querySelector('[aria-label="Canonical datasets and leases"]');
  return {
    url: window.location.pathname + window.location.hash, section: section(), scope: captureOperatorIncidentScope(),
    retainedNodeConnected: retainedNode?.isConnected ?? null,
    sameCanonicalNode: retainedNode ? node === retainedNode : null,
    // Read-only actual fibers, not a wrapper or a fake lifecycle hook. React's
    // alternate is the same retained instance across commits, not a remount.
    controls: lineage(node), view: lineage(node?.querySelector("input") ?? null),
    draft: node?.querySelector("input")?.value ?? null,
    clients: clients.map((client, index) => ({ instance: index + 1, current: client.current(), revision: client.viewRevision() })),
  };
}
function record(label: string) { checkpoints.push({ label, ...observe() }); }

beforeEach(() => {
  const rect = { x: 0, y: 0, width: 1024, height: 700, top: 0, left: 0, right: 1024, bottom: 700, toJSON: () => ({}) };
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(rect);
  vi.stubGlobal("ResizeObserver", class {
    constructor(private callback: ResizeObserverCallback) {}
    observe(target: Element) { this.callback([{ target, contentRect: rect } as ResizeObserverEntry], this as unknown as ResizeObserver); }
    unobserve() {}
    disconnect() {}
  });
  window.history.replaceState(null, "", "/settings#dataPaths");
  useAuthStore.setState({ status: "logged-in", token: "synthetic-r36", username: "synthetic", sessionGeneration: 10 });
  useBrokerStore.setState({ activeAccountId: "native:synthetic:A" });
  useConnectionStore.setState({ apiKey: "" });
  useModeStore.setState({ mode: "practice" });
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  failures = []; clients = []; checkpoints = []; commits = [];
  retainedNode = null; fiberIds = new WeakMap(); nextFiberId = 0;
  const datasets = CanonicalDataClient.prototype.datasets;
  vi.spyOn(CanonicalDataClient.prototype, "datasets").mockImplementation(function (this: CanonicalDataClient) {
    if (!clients.includes(this)) clients.push(this);
    return datasets.call(this);
  });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    try {
      expect(`${init.method ?? "GET"} ${url}`).toBe(`GET ${base}/datasets`);
      expect(new Headers(init.headers).get("Authorization")).toBe("Bearer synthetic-r36");
      return new Response(JSON.stringify({ status: "success", data: catalogue }));
    } catch (error) { failures.push(error); throw error; }
  }));
});
afterEach(async ({ task }) => {
  // Raw scope/section transitions are retained even on RED; no reconstructed
  // success record or timing-based interpretation is substituted.
  Object.assign(task.meta, { r36: { checkpoints, commits, clients: clients.map(client => ({ current: client.current(), revision: client.viewRevision() })) } });
  cleanup(); await act(async () => {}); queryClient.clear();
  vi.restoreAllMocks(); vi.unstubAllGlobals(); expect(failures).toEqual([]);
});
async function mount() {
  render(<QueryClientProvider client={queryClient}><BrowserRouter><Link to="/learn#different-app">Learn</Link><Link to="/settings">Settings app</Link><Link to="/settings#general">General deep link</Link><Profiler id="apps" onRender={() => { commits.push(observe()); }}><UnifiedAppsHost /></Profiler></BrowserRouter></QueryClientProvider>);
  await screen.findByText(/No qualified datasets available/);
}

it("retains the canonical component when browser Back restores Settings in a stable scope", async () => {
  await mount();
  const node = screen.getByRole("region", { name: "Canonical datasets and leases" });
  retainedNode = node;
  const input = screen.getByLabelText("Immutable history snapshot ID");
  fireEvent.change(input, { target: { value: "unsubmitted-snapshot-draft" } });
  const before = captureOperatorIncidentScope();
  const beforeControls = lineage(node);
  const beforeView = lineage(input);
  record("before");
  fireEvent.click(screen.getByRole("link", { name: "Learn" }));
  await screen.findByText("Other app");
  expect(node).not.toBeVisible();
  record("hidden");
  expect.soft(node.isConnected, "hidden background renders must retain Settings").toBe(true);
  await act(async () => { window.history.back(); });
  await waitFor(() => expect(window.location.pathname + window.location.hash).toBe("/settings#dataPaths"));
  await screen.findByText(/No qualified datasets available/);
  record("return");
  expect(captureOperatorIncidentScope()).toEqual(before);
  expect(clients).toHaveLength(2);
  expect(clients[0].current()).toBe(false);
  expect(clients[0].viewRevision()).toBeGreaterThan(0);
  expect(clients[1].current()).toBe(true);
  expect.soft(screen.getByRole("region", { name: "Canonical datasets and leases" })).toBe(node);
  expect.soft(lineage(screen.getByRole("region", { name: "Canonical datasets and leases" }))).toEqual(beforeControls);
  expect.soft(lineage(screen.getByLabelText("Immutable history snapshot ID"))).toEqual(beforeView);
  expect.soft(screen.getByLabelText("Immutable history snapshot ID")).toHaveValue("unsubmitted-snapshot-draft");
});

it("retains the selected Settings section on a generic app return without a hash", async () => {
  await mount();
  const node = screen.getByRole("region", { name: "Canonical datasets and leases" });
  retainedNode = node;
  record("before");
  fireEvent.click(screen.getByRole("link", { name: "Learn" }));
  await screen.findByText("Other app"); record("hidden");
  fireEvent.click(screen.getByRole("link", { name: "Settings app" }));
  await waitFor(() => expect(screen.getByRole("region", { name: /^Settings$/ })).toBeVisible());
  record("return");
  expect.soft(section()).toBe("settings-tabpanel-dataPaths");
  expect.soft(screen.queryByRole("region", { name: "Canonical datasets and leases" })).toBe(node);
});

it("selects an explicit different Settings hash after hiding rather than freezing the retained section", async () => {
  await mount();
  fireEvent.click(screen.getByRole("link", { name: "Learn" }));
  await screen.findByText("Other app");
  fireEvent.click(screen.getByRole("link", { name: "General deep link" }));
  await waitFor(() => expect(section()).toBe("settings-tabpanel-general"));
  expect(screen.queryByRole("region", { name: "Canonical datasets and leases" })).not.toBeInTheDocument();
  expect(clients.every(client => !client.current())).toBe(true);
});

it.each(["account", "session", "mode", "backend", "account round trip"])("retires the private inner draft when %s changes while Settings is hidden", async change => {
  await mount();
  const input = screen.getByLabelText("Immutable history snapshot ID");
  fireEvent.change(input, { target: { value: "private-old-scope" } });
  const before = captureOperatorIncidentScope();
  const oldView = lineage(input).find(item => item.component === "DataView");
  fireEvent.click(screen.getByRole("link", { name: "Learn" }));
  await screen.findByText("Other app");
  const readCount = vi.mocked(fetch).mock.calls.length;
  await act(async () => {
    if (change === "account" || change === "account round trip") useBrokerStore.setState({ activeAccountId: "native:synthetic:B" });
    if (change === "account round trip") useBrokerStore.setState({ activeAccountId: "native:synthetic:A" });
    if (change === "session") useAuthStore.setState({ sessionGeneration: 11 });
    if (change === "mode") useModeStore.setState({ mode: "live" });
    if (change === "backend") useConnectionStore.setState({ apiKey: "synthetic-replacement" });
  });
  expect(captureOperatorIncidentScope().generation).toBeGreaterThan(before.generation);
  expect(vi.mocked(fetch).mock.calls).toHaveLength(readCount);
  expect(clients.every(client => !client.current())).toBe(true);
  // Retirement must destroy the private owner now, not just clear its draft
  // when Activity reconnects. Session/backend and batched A→B→A have no scalar
  // account/mode change to wake the retained docking route.
  expect.soft(input.isConnected, "retired private DataView must be destroyed before app return").toBe(false);
  expect.soft(document.querySelector('[aria-label="Canonical datasets and leases"] input')).toBeNull();
  record(`hidden retirement ${change}`);
  fireEvent.click(screen.getByRole("link", { name: "Settings app" }));
  await screen.findByText(/No qualified datasets available/);
  const replacement = screen.getByLabelText("Immutable history snapshot ID");
  expect(replacement).not.toBe(input);
  expect(lineage(replacement).find(item => item.component === "DataView")).not.toEqual(oldView);
  expect(replacement).toHaveValue("");
  expect(clients[0].current()).toBe(false);
  expect(clients.at(-1)!.current()).toBe(true);
  expect(commits.filter(item => {
    const commit = item as ReturnType<typeof observe>;
    return commit.scope.generation !== before.generation && commit.url.startsWith("/settings") && commit.draft === "private-old-scope";
  })).toEqual([]);
  record(`retired ${change}`);
});
