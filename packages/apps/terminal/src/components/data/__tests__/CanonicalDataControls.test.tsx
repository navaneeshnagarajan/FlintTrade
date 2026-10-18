import { Activity, Profiler, StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider, onlineManager } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DataSection } from "@/tools/Settings/DataSection";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";

vi.mock("@/tools/Settings/WatchlistManagerPanel", () => ({ WatchlistManagerPanel: () => <p>Retained watchlist manager</p> }));
const base = "/ft-api/api/v1/data";
const snapshotId = "c".repeat(64);
const datasetId = `history:${snapshotId}`;
const leaseId = "1".repeat(32);
const scope = { principal_id: "synthetic-operator", environment: "local_history", account_id: null, run_id: null, generation: 4 };
const identity = { instrument_id: "synthetic-series", venue: "test-venue", asset_class: "equity", currency: "USD", quantity_unit: "shares", price_unit: "USD/share", adjustment: "raw", calendar_id: "synthetic-calendar", calendar_revision: "1", interval_seconds: 60, multiplier: "1" };
const source = { connection_id: "local-history", provider: "recorded_history", environment: "local_history", account_id: null, auth_generation: 4, configuration_generation: 0 };
const observed = "2026-01-02T10:00:00+00:00";
const retrieved = "2026-01-02T10:01:00+00:00";
const bar = { timestamp: observed, open: 10, high: 12, low: 9, close: 11, volume: 0.25, oi: null, published_at: null };
const manifest = { schema_version: 1, snapshot_id: snapshotId, scope, identity, policy: { mode: "single", duplicates: "identical_only", conflicts: "reject", revision: "1", priority: [source.connection_id], sessions: [{ start: observed, end: retrieved }] }, contributors: [{ source, identity, revision: "1", status: "available", retrieved_at: retrieved, bars: [bar] }], bars: [{ ...bar, source_id: source.connection_id, source_revision: "1", retrieved_at: retrieved }], status: "available", coverage: { expected: 1, observed: 1, missing: [] }, duplicates: { [source.connection_id]: 0 }, conflicts: [], rights: "not_attested", execution_authority: false };
const snapshot = { dataset_id: datasetId, identity, source, scope, policy_revision: snapshotId, status: "stale", reason: "expired", age_seconds: 600, expires_at: 1791644000, sequence: 0, observed_at: observed, published_at: null, retrieved_at: retrieved, payload: manifest, updates: [], replay_gap: false };
const catalog = { scope, datasets: [{ dataset_id: datasetId, snapshot_id: snapshotId, source_kind: "recorded_history", label: "Recorded history — not a live broker feed", identity, coverage: manifest.coverage, status: "available", execution_authority: false }, { dataset_id: "native:ticks", source_kind: "native", status: "unavailable", label: "Native ticks — unavailable until read cutover", reason: "native_read_cutover_unavailable", execution_authority: false }], legacy_history: "unqualified_legacy", portfolio: "Explicit imported/manual records; not a broker book" };
const reply = (data: unknown, status = 200) => new Response(JSON.stringify({ status: "success", data }), { status });
const missing = () => new Response(JSON.stringify({ status: "unavailable", code: "dataset_or_lease_retired" }), { status: 404 });
class SyntheticNetworkFailure extends Error {}
type Handler = (init: RequestInit) => Response | Promise<Response>;
let handlers: Map<string, Handler>;
let calls: string[];
let failures: unknown[];
let queryClient: QueryClient;
let authorisedHeader: string;
beforeEach(() => {
  useAuthStore.setState({ status: "logged-in", token: "synthetic-A", username: "synthetic", sessionGeneration: 4 });
  useConnectionStore.setState({ apiKey: "" });
  useBrokerStore.setState({ activeAccountId: "native:synthetic:A" });
  useModeStore.setState({ mode: "live" });
  authorisedHeader = "Bearer synthetic-A";
  calls = []; failures = [];
  handlers = new Map<string, Handler>([
    [`GET ${base}/datasets`, () => reply(catalog)],
    [`POST ${base}/leases`, init => { expect(JSON.parse(String(init.body))).toEqual({ dataset_id: datasetId }); return reply({ lease_id: leaseId, snapshot }, 201); }],
    [`GET ${base}/leases/${leaseId}`, () => reply(snapshot)],
    [`DELETE ${base}/leases/${leaseId}`, () => { handlers.set(`GET ${base}/leases/${leaseId}`, missing); return reply({ released: true }); }],
  ]);
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const key = `${init.method ?? "GET"} ${url}`; calls.push(key);
    try {
      const handler = handlers.get(key); expect(handler, `Unregistered transport: ${key}`).toBeDefined();
      expect(new Headers(init.headers).get("Authorization")).toBe(authorisedHeader);
      expect(init.credentials).toBe("omit"); expect(init.cache).toBe("no-store");
      return await handler!(init);
    } catch (error) { if (!(error instanceof SyntheticNetworkFailure)) failures.push(error); throw error; }
  }));
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
});
afterEach(async () => { cleanup(); await act(async () => {}); queryClient.clear(); vi.unstubAllGlobals(); expect(failures).toEqual([]); });
function mount() { return render(<QueryClientProvider client={queryClient}><MemoryRouter><DataSection settings={{ fastStoragePath: "", archiveStoragePath: "" }} onChange={vi.fn()} /></MemoryRouter></QueryClientProvider>); }
async function acquire() {
  fireEvent.click(await screen.findByRole("button", { name: `Acquire ${datasetId}` }));
  await screen.findByText(new RegExp(`Lease: ${leaseId}`));
}
it("retires cached acquisition controls offline and rereads honestly on return", async () => {
  mount(); await screen.findByRole("button", { name: `Acquire ${datasetId}` });
  try {
    await act(async () => { onlineManager.setOnline(false); });
    expect(screen.queryByRole("button", { name: `Acquire ${datasetId}` })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/offline/i);
    expect(calls).toEqual([`GET ${base}/datasets`]);
    handlers.set(`GET ${base}/datasets`, () => reply({ ...catalog, datasets: [] }));
    await act(async () => { onlineManager.setOnline(true); });
    expect(await screen.findByText(/No qualified datasets available/)).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(calls).toEqual([`GET ${base}/datasets`, `GET ${base}/datasets`]);
  } finally { await act(async () => { onlineManager.setOnline(true); }); }
});
it("keeps mounted Settings acquisition usable after StrictMode effect retirement", async () => {
  render(<StrictMode><QueryClientProvider client={queryClient}><MemoryRouter><DataSection settings={{ fastStoragePath: "", archiveStoragePath: "" }} onChange={vi.fn()} /></MemoryRouter></QueryClientProvider></StrictMode>);
  await acquire();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Release exact lease" }));
  expect(await screen.findByText(/Release confirmed by exact readback/)).toBeVisible();
  expect(calls.filter(call => call.startsWith("POST"))).toEqual([`POST ${base}/leases`]);
  expect(calls.filter(call => call.startsWith("DELETE"))).toEqual([`DELETE ${base}/leases/${leaseId}`]);
});
it("mounts canonical controls without replacing storage or downloads and binds lease receipt/readback/release", async () => {
  mount();
  expect(await screen.findByRole("heading", { name: "Canonical datasets and leases" })).toBeVisible();
  expect(screen.getByLabelText("Fast storage path")).toBeVisible();
  expect(screen.getByText("Retained watchlist manager")).toBeVisible();
  expect(screen.getByRole("link", { name: "Open downloads and datasets in Testing" })).toBeVisible();
  await acquire();
  expect(screen.getByText(/Freshness: stale/)).toBeVisible();
  expect(screen.getByText(/Sequence: 0/)).toBeVisible();
  expect(screen.getByText(/Published: unavailable/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Acquire native:ticks" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Release exact lease" }));
  expect(await screen.findByText(/Release confirmed by exact readback/)).toBeVisible();
  expect(calls).toEqual([`GET ${base}/datasets`, `POST ${base}/leases`, `GET ${base}/leases/${leaseId}`, `DELETE ${base}/leases/${leaseId}`, `GET ${base}/leases/${leaseId}`]);
  expect(useModeStore.getState().mode).toBe("live");
  expect(useBrokerStore.getState().activeAccountId).toBe("native:synthetic:A");
});
it("reads ordered updates with the exact cursor and displays replay loss without switching sources", async () => {
  const update = { sequence: 3, kind: "snapshot", observed_at: observed, published_at: null, retrieved_at: retrieved, payload: manifest };
  handlers.set(`GET ${base}/leases/${leaseId}?after_sequence=0`, () => reply({ ...snapshot, sequence: 3, updates: [update], replay_gap: true }));
  mount(); await acquire(); fireEvent.click(screen.getByRole("button", { name: "Read lease updates" }));
  expect(await screen.findByText(/Sequence: 3/)).toBeVisible();
  expect(screen.getByText(/Replay gap detected/)).toBeVisible();
  expect(calls.filter(call => call.startsWith("POST"))).toHaveLength(1);
});
it("inspects the exact immutable manifest and retains missing values and provenance", async () => {
  handlers.set(`GET /ft-api/v1/historify/snapshots/${snapshotId}`, () => reply(manifest));
  mount(); await screen.findByRole("button", { name: `Acquire ${datasetId}` });
  fireEvent.change(screen.getByLabelText("Immutable history snapshot ID"), { target: { value: snapshotId } });
  fireEvent.click(screen.getByRole("button", { name: "Inspect exact manifest" }));
  expect(await screen.findByText(/Manifest readback:/)).toHaveTextContent(snapshotId);
  expect(screen.getByText(/Manifest status: available/)).toBeVisible();
  expect(screen.getByText(/Rights: not_attested/)).toBeVisible();
  expect(screen.getByLabelText("Exact immutable manifest")).toHaveTextContent('"oi": null');
  expect(screen.getByLabelText("Exact immutable manifest")).toHaveTextContent('"volume": 0.25');
  expect(calls).toEqual([`GET ${base}/datasets`, `GET /ft-api/v1/historify/snapshots/${snapshotId}`]);
});
it.each([
  ["wrong ID", { ...manifest, snapshot_id: "d".repeat(64) }],
  ["foreign scope", { ...manifest, scope: { ...scope, generation: 9 } }],
  ["missing identity", { ...manifest, identity: { ...identity, currency: undefined } }],
  ["missing price metadata", { ...manifest, bars: [{ ...manifest.bars[0], oi: undefined }] }],
  ["incoherent prices", { ...manifest, bars: [{ ...manifest.bars[0], close: 99 }] }],
  ["coverage mismatch", { ...manifest, coverage: { ...manifest.coverage, observed: 8 } }],
  ["relabelled contributor", { ...manifest, contributors: [{ ...manifest.contributors[0], identity: { ...identity, venue: "other" } }] }],
])("refuses a %s manifest rather than displaying qualifying evidence", async (_reason, data) => {
  handlers.set(`GET /ft-api/v1/historify/snapshots/${snapshotId}`, () => reply(data));
  mount(); await screen.findByRole("button", { name: `Acquire ${datasetId}` });
  fireEvent.change(screen.getByLabelText("Immutable history snapshot ID"), { target: { value: snapshotId } });
  fireEvent.click(screen.getByRole("button", { name: "Inspect exact manifest" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/invalid|mismatch|incomplete/i);
  expect(screen.queryByText(/Manifest readback:/)).not.toBeInTheDocument();
});
it("retains partial immutable coverage without promoting it to complete history", async () => {
  handlers.set(`GET /ft-api/v1/historify/snapshots/${snapshotId}`, () => reply({ ...manifest, status: "partial", coverage: { expected: 2, observed: 1, missing: [retrieved] } }));
  mount(); await screen.findByRole("button", { name: `Acquire ${datasetId}` });
  fireEvent.change(screen.getByLabelText("Immutable history snapshot ID"), { target: { value: snapshotId } });
  fireEvent.click(screen.getByRole("button", { name: "Inspect exact manifest" }));
  expect(await screen.findByText(/Manifest status: partial/)).toHaveTextContent("1/2");
});
it.each([
  ["suppressed replay gap", { ...snapshot, sequence: 3, updates: [{ sequence: 3, kind: "snapshot", observed_at: observed, retrieved_at: retrieved, payload: manifest }], replay_gap: false }],
  ["regressive sequence", { ...snapshot, sequence: null, status: "unavailable" }],
  ["conflicting sequence", { ...snapshot, payload: { ...manifest, snapshot_id: "d".repeat(64) } }],
  ["source switch", { ...snapshot, source: { ...source, connection_id: "different" } }],
])("refuses %s while retaining the prior exact handle for release", async (_reason, data) => {
  handlers.set(`GET ${base}/leases/${leaseId}?after_sequence=0`, () => reply(data));
  mount(); await acquire(); fireEvent.click(screen.getByRole("button", { name: "Read lease updates" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/invalid|mismatch|sequence|incomplete/);
  expect(screen.getByText(/Sequence: 0/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Release exact lease" })).toBeEnabled();
});
it("refuses a lease containing a relabelled immutable history payload and releases its exact handle", async () => {
  const incorrect = { ...snapshot, payload: { ...manifest, snapshot_id: "d".repeat(64) } };
  handlers.set(`POST ${base}/leases`, () => reply({ lease_id: leaseId, snapshot: incorrect }, 201));
  handlers.set(`GET ${base}/leases/${leaseId}`, () => reply(incorrect));
  mount(); fireEvent.click(await screen.findByRole("button", { name: `Acquire ${datasetId}` }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/mismatch|invalid/i);
  expect(calls).toContain(`DELETE ${base}/leases/${leaseId}`);
});
it("retains an unverified receipt handle and blocks acquisition when failed-read cleanup is unknown", async () => {
  handlers.set(`GET ${base}/leases/${leaseId}`, () => new Response("{}", { status: 503 }));
  handlers.set(`DELETE ${base}/leases/${leaseId}`, () => new Response("{}", { status: 503 }));
  mount(); fireEvent.click(await screen.findByRole("button", { name: `Acquire ${datasetId}` }));
  expect(await screen.findByRole("alert")).toHaveTextContent("release outcome unknown");
  expect(screen.getByRole("button", { name: `Acquire ${datasetId}` })).toBeDisabled();
  expect(screen.getByRole("button", { name: `Release unconfirmed lease ${leaseId}` })).toBeEnabled();
  handlers.set(`DELETE ${base}/leases/${leaseId}`, () => { handlers.set(`GET ${base}/leases/${leaseId}`, missing); return reply({ released: true }); });
  fireEvent.click(screen.getByRole("button", { name: `Release unconfirmed lease ${leaseId}` }));
  expect(await screen.findByText(/Release confirmed by exact readback/)).toBeVisible();
});
it.each([403, 503])("renders dataset HTTP %s refusal without offering invented acquisitions", async status => {
  handlers.set(`GET ${base}/datasets`, () => new Response(JSON.stringify({ status: "error", code: "data_scope_unavailable" }), { status }));
  mount(); expect(await screen.findByRole("alert")).toHaveTextContent("data_scope_unavailable");
  expect(screen.queryByRole("button", { name: `Acquire ${datasetId}` })).not.toBeInTheDocument();
  expect(calls).toEqual([`GET ${base}/datasets`]);
});
it("permits explicit reacquisition after exact expired-lease readback without claiming a release", async () => {
  mount(); await acquire();
  handlers.set(`GET ${base}/leases/${leaseId}?after_sequence=0`, missing);
  fireEvent.click(screen.getByRole("button", { name: "Read lease updates" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/absent or retired/);
  expect(screen.getByRole("button", { name: `Acquire ${datasetId}` })).toBeEnabled();
  expect(screen.queryByText(/Release confirmed by exact readback/)).not.toBeInTheDocument();
  expect(calls.filter(call => call.startsWith("POST"))).toHaveLength(1);
});
it("reconciles already-retired release receipts as absence, not confirmed release", async () => {
  mount(); await acquire();
  handlers.set(`DELETE ${base}/leases/${leaseId}`, () => { handlers.set(`GET ${base}/leases/${leaseId}`, missing); return reply({ released: false }); });
  fireEvent.click(screen.getByRole("button", { name: "Release exact lease" }));
  expect(await screen.findByText(/Lease already absent or retired/)).toBeVisible();
  expect(screen.getByRole("button", { name: `Acquire ${datasetId}` })).toBeEnabled();
  expect(screen.queryByText(/Release confirmed by exact readback/)).not.toBeInTheDocument();
});
it("refuses a decoded old catalogue after Activity return without poisoning the fresh generation", async () => {
  let finish!: (body: unknown) => void;
  const held = reply(catalog);
  vi.spyOn(held, "json").mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  handlers.set(`GET ${base}/datasets`, () => held);
  const element = (mode: "visible" | "hidden") => <QueryClientProvider client={queryClient}><Activity mode={mode}><MemoryRouter><DataSection settings={{ fastStoragePath: "", archiveStoragePath: "" }} onChange={vi.fn()} /></MemoryRouter></Activity></QueryClientProvider>;
  const view = render(element("visible"));
  await waitFor(() => expect(finish).toBeDefined());
  try {
    view.rerender(element("hidden"));
    handlers.set(`GET ${base}/datasets`, () => reply(catalog));
    view.rerender(element("visible"));
    expect(await screen.findByRole("button", { name: `Acquire ${datasetId}` })).toBeEnabled();
    await act(async () => { finish({ status: "success", data: { ...catalog, datasets: [], scope: { ...scope, generation: 99 } } }); });
    expect(screen.getByRole("button", { name: `Acquire ${datasetId}` })).toBeEnabled();
    expect(screen.queryByText(/No qualified datasets/)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(calls).toEqual([`GET ${base}/datasets`, `GET ${base}/datasets`]);
  } finally { finish({ status: "success", data: catalog }); }
});
it("refuses a late lease-read body after Activity return and permits a distinct explicit acquisition", async () => {
  let finish!: (body: unknown) => void;
  const held = reply(snapshot);
  vi.spyOn(held, "json").mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  handlers.set(`GET ${base}/leases/${leaseId}?after_sequence=0`, () => held);
  const element = (mode: "visible" | "hidden") => <QueryClientProvider client={queryClient}><Activity mode={mode}><MemoryRouter><DataSection settings={{ fastStoragePath: "", archiveStoragePath: "" }} onChange={vi.fn()} /></MemoryRouter></Activity></QueryClientProvider>;
  const view = render(element("visible")); await acquire();
  fireEvent.click(screen.getByRole("button", { name: "Read lease updates" }));
  await waitFor(() => expect(finish).toBeDefined());
  const nextId = "2".repeat(32);
  try {
    view.rerender(element("hidden"));
    await waitFor(() => expect(calls.filter(call => call === `GET ${base}/leases/${leaseId}`)).toHaveLength(2));
    handlers.set(`POST ${base}/leases`, () => reply({ lease_id: nextId, snapshot }, 201));
    handlers.set(`GET ${base}/leases/${nextId}`, () => reply(snapshot));
    handlers.set(`DELETE ${base}/leases/${nextId}`, () => { handlers.set(`GET ${base}/leases/${nextId}`, missing); return reply({ released: true }); });
    view.rerender(element("visible"));
    fireEvent.click(await screen.findByRole("button", { name: `Acquire ${datasetId}` }));
    expect(await screen.findByText(new RegExp(`Lease: ${nextId}`))).toBeVisible();
    await act(async () => { finish({ status: "success", data: { ...snapshot, sequence: 3 } }); });
    expect(screen.getByText(new RegExp(`Lease: ${nextId}`))).toBeVisible();
    expect(screen.queryByText(new RegExp(`Lease: ${leaseId}`))).not.toBeInTheDocument();
    expect(screen.getByText(/Sequence: 0/)).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(calls.filter(call => call.startsWith("POST"))).toHaveLength(2);
  } finally { finish({ status: "success", data: snapshot }); }
});
it.each(["account", "session"])("keeps a decoded catalogue from a retired %s out of the replacement scope", async retirement => {
  let finish!: (body: unknown) => void;
  const held = reply(catalog);
  vi.spyOn(held, "json").mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  handlers.set(`GET ${base}/datasets`, () => held);
  mount(); await waitFor(() => expect(finish).toBeDefined());
  try {
    handlers.set(`GET ${base}/datasets`, () => reply({ ...catalog, datasets: [] }));
    await act(async () => {
      if (retirement === "account") useBrokerStore.setState({ activeAccountId: "native:synthetic:B" });
      else useAuthStore.setState({ sessionGeneration: 5 });
    });
    expect(await screen.findByText(/No qualified datasets available/)).toBeVisible();
    await act(async () => { finish({ status: "success", data: catalog }); });
    expect(screen.queryByRole("button", { name: `Acquire ${datasetId}` })).not.toBeInTheDocument();
    expect(calls).toEqual([`GET ${base}/datasets`, `GET ${base}/datasets`]);
  } finally { finish({ status: "success", data: catalog }); }
});
it.each(["malformed", "transport", "refused"])("keeps a %s catalogue closed after StrictMode instead of labelling it empty", async problem => {
  handlers.set(`GET ${base}/datasets`, () => {
    if (problem === "transport") throw new SyntheticNetworkFailure("catalogue transport unavailable");
    if (problem === "refused") return new Response(JSON.stringify({ status: "error", code: "data_scope_unavailable" }), { status: 503 });
    return reply({ ...catalog, datasets: null });
  });
  render(<StrictMode><QueryClientProvider client={queryClient}><MemoryRouter><DataSection settings={{ fastStoragePath: "", archiveStoragePath: "" }} onChange={vi.fn()} /></MemoryRouter></QueryClientProvider></StrictMode>);
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(screen.queryByText(/No qualified datasets/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Acquire / })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Inspect exact manifest" })).toBeDisabled();
  expect(calls).toEqual([`GET ${base}/datasets`]);
});
it("retains the inner draft through held retirement but never the old manifest or lease", async () => {
  let finish!: (response: Response) => void;
  let resuming = false;
  const resumedCommits: string[] = [];
  handlers.set(`GET /ft-api/v1/historify/snapshots/${snapshotId}`, () => reply(manifest));
  const element = (mode: "visible" | "hidden") => <QueryClientProvider client={queryClient}><Profiler id="data" onRender={() => { if (resuming) resumedCommits.push(document.querySelector('[aria-label="Canonical datasets and leases"]')?.textContent ?? ""); }}><Activity mode={mode}><MemoryRouter><DataSection settings={{ fastStoragePath: "", archiveStoragePath: "" }} onChange={vi.fn()} /></MemoryRouter></Activity></Profiler></QueryClientProvider>;
  const view = render(element("visible")); await acquire();
  const input = screen.getByLabelText("Immutable history snapshot ID");
  fireEvent.change(input, { target: { value: snapshotId } });
  fireEvent.click(screen.getByRole("button", { name: "Inspect exact manifest" }));
  await screen.findByText(/Manifest readback:/);
  handlers.set(`DELETE ${base}/leases/${leaseId}`, () => new Promise(resolve => { finish = resolve; }));
  try {
    view.rerender(element("hidden"));
    await waitFor(() => expect(finish).toBeDefined());
    resuming = true;
    view.rerender(element("visible"));
    await act(async () => {});
    expect.soft(screen.queryByLabelText("Immutable history snapshot ID")).toBe(input);
    expect.soft(input).toHaveValue(snapshotId);
    expect(screen.queryByText(/Manifest readback:/)).not.toBeInTheDocument();
    expect(screen.queryByText(new RegExp(`Lease: ${leaseId}`))).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: `Acquire ${datasetId}` })).not.toBeInTheDocument();
    handlers.set(`GET ${base}/leases/${leaseId}`, missing);
    await act(async () => { finish(reply({ released: true })); });
    expect(await screen.findByRole("button", { name: `Acquire ${datasetId}` })).toBeEnabled();
    expect.soft(screen.getByLabelText("Immutable history snapshot ID")).toBe(input);
    expect.soft(screen.getByLabelText("Immutable history snapshot ID")).toHaveValue(snapshotId);
    expect(screen.queryByText(/Manifest readback:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Release confirmed/)).not.toBeInTheDocument();
    expect(resumedCommits.length).toBeGreaterThan(0);
    expect(resumedCommits.every(text => !text.includes("Manifest readback:") && !text.includes("Lease:") && !text.includes("Freshness:") && !text.includes("Release confirmed"))).toBe(true);
    expect(calls).toEqual([`GET ${base}/datasets`, `POST ${base}/leases`, `GET ${base}/leases/${leaseId}`, `GET /ft-api/v1/historify/snapshots/${snapshotId}`, `DELETE ${base}/leases/${leaseId}`, `GET ${base}/leases/${leaseId}`, `GET ${base}/datasets`]);
  } finally { finish?.(reply({ released: true })); }
});
it("waits for late acquisition retirement before opening an Activity replacement", async () => {
  let finish!: (response: Response) => void;
  handlers.set(`POST ${base}/leases`, () => new Promise(resolve => { finish = resolve; }));
  const element = (mode: "visible" | "hidden") => <QueryClientProvider client={queryClient}><Activity mode={mode}><MemoryRouter><DataSection settings={{ fastStoragePath: "", archiveStoragePath: "" }} onChange={vi.fn()} /></MemoryRouter></Activity></QueryClientProvider>;
  const view = render(element("visible"));
  fireEvent.click(await screen.findByRole("button", { name: `Acquire ${datasetId}` }));
  await waitFor(() => expect(finish).toBeDefined());
  view.rerender(element("hidden")); view.rerender(element("visible"));
  await act(async () => {});
  expect(screen.queryByRole("button", { name: `Acquire ${datasetId}` })).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(/retir/i);
  await act(async () => { finish(reply({ lease_id: leaseId, snapshot }, 201)); });
  expect(await screen.findByRole("button", { name: `Acquire ${datasetId}` })).toBeEnabled();
  expect(screen.queryByText(new RegExp(`Lease: ${leaseId}`))).not.toBeInTheDocument();
  expect(calls).toEqual([`GET ${base}/datasets`, `POST ${base}/leases`, `DELETE ${base}/leases/${leaseId}`, `GET ${base}/leases/${leaseId}`, `GET ${base}/datasets`]);
});
it("blocks Activity return until an uncertain old lease is explicitly released", async () => {
  const element = (mode: "visible" | "hidden") => <QueryClientProvider client={queryClient}><Activity mode={mode}><MemoryRouter><DataSection settings={{ fastStoragePath: "", archiveStoragePath: "" }} onChange={vi.fn()} /></MemoryRouter></Activity></QueryClientProvider>;
  const view = render(element("visible")); await acquire();
  handlers.set(`DELETE ${base}/leases/${leaseId}`, () => { throw new SyntheticNetworkFailure("lost cleanup"); });
  view.rerender(element("hidden"));
  await waitFor(() => expect(calls).toContain(`DELETE ${base}/leases/${leaseId}`));
  view.rerender(element("visible"));
  expect(await screen.findByRole("alert")).toHaveTextContent(/unresolved/i);
  expect(screen.queryByRole("button", { name: `Acquire ${datasetId}` })).not.toBeInTheDocument();
  expect(calls.filter(call => call === `GET ${base}/datasets`)).toHaveLength(1);
  handlers.set(`DELETE ${base}/leases/${leaseId}`, () => { handlers.set(`GET ${base}/leases/${leaseId}`, missing); return reply({ released: true }); });
  fireEvent.click(screen.getByRole("button", { name: "Retry exact retired-lease cleanup" }));
  expect(await screen.findByRole("button", { name: `Acquire ${datasetId}` })).toBeEnabled();
  expect(calls.filter(call => call.startsWith("POST"))).toHaveLength(1);
  expect(calls.filter(call => call.startsWith("DELETE"))).toHaveLength(2);
});
it("returns from an Activity-hidden app without presenting a released lease or reacquiring silently", async () => {
  const element = (mode: "visible" | "hidden") => <QueryClientProvider client={queryClient}><Activity mode={mode}><MemoryRouter><DataSection settings={{ fastStoragePath: "", archiveStoragePath: "" }} onChange={vi.fn()} /></MemoryRouter></Activity></QueryClientProvider>;
  const view = render(element("visible")); await acquire();
  view.rerender(element("hidden"));
  await waitFor(() => expect(calls.filter(call => call === `GET ${base}/leases/${leaseId}`)).toHaveLength(2));
  view.rerender(element("visible"));
  expect(await screen.findByRole("button", { name: `Acquire ${datasetId}` })).toBeEnabled();
  expect(screen.queryByText(new RegExp(`Lease: ${leaseId}`))).not.toBeInTheDocument();
  expect(calls.filter(call => call.startsWith("POST"))).toHaveLength(1);
});
it.each(["close", "account", "session"])("releases the exact lease on %s retirement without borrowing new credentials", async retirement => {
  const view = mount(); await acquire();
  await act(async () => {
    if (retirement === "close") view.unmount();
    else if (retirement === "account") useBrokerStore.setState({ activeAccountId: "native:synthetic:B" });
    else useAuthStore.setState({ status: "pin-required", token: null, sessionGeneration: 5 });
  });
  await waitFor(() => expect(calls).toContain(`DELETE ${base}/leases/${leaseId}`));
  await waitFor(() => expect(calls.filter(call => call === `GET ${base}/leases/${leaseId}`)).toHaveLength(2));
  expect(screen.queryByText(new RegExp(`Lease: ${leaseId}`))).not.toBeInTheDocument();
});
it("releases a lease whose creation response arrives after its view closed", async () => {
  let finish!: (response: Response) => void;
  handlers.set(`POST ${base}/leases`, () => new Promise(resolve => { finish = resolve; }));
  const view = mount(); fireEvent.click(await screen.findByRole("button", { name: `Acquire ${datasetId}` }));
  await waitFor(() => expect(finish).toBeDefined()); view.unmount();
  await act(async () => { finish(reply({ lease_id: leaseId, snapshot }, 201)); });
  await waitFor(() => expect(calls).toContain(`DELETE ${base}/leases/${leaseId}`));
  expect(calls).toEqual([`GET ${base}/datasets`, `POST ${base}/leases`, `DELETE ${base}/leases/${leaseId}`, `GET ${base}/leases/${leaseId}`]);
});
it.each(["malformed", "foreign", "failed-read"])("releases the received handle after a %s acquisition receipt/readback", async problem => {
  if (problem === "failed-read") handlers.set(`GET ${base}/leases/${leaseId}`, () => new Response("{}", { status: 503 }));
  else handlers.set(`POST ${base}/leases`, () => reply({ lease_id: leaseId, snapshot: problem === "malformed" ? { dataset_id: datasetId } : { ...snapshot, scope: { ...scope, generation: 9 } } }, 201));
  mount(); fireEvent.click(await screen.findByRole("button", { name: `Acquire ${datasetId}` }));
  await screen.findByRole("alert");
  await waitFor(() => expect(calls).toContain(`DELETE ${base}/leases/${leaseId}`));
  expect(screen.queryByText(new RegExp(`Lease: ${leaseId}`))).not.toBeInTheDocument();
});
it("retains the exact handle when release outcome is unknown instead of confirming a timeout", async () => {
  let rejectRelease!: (error: Error) => void;
  handlers.set(`DELETE ${base}/leases/${leaseId}`, () => new Promise((_resolve, reject) => { rejectRelease = reject; }));
  mount(); await acquire(); fireEvent.click(screen.getByRole("button", { name: "Release exact lease" }));
  await waitFor(() => expect(rejectRelease).toBeDefined());
  // Network faults are intentional, not an assertion failure inside the stub.
  await act(async () => { rejectRelease(new SyntheticNetworkFailure("synthetic lost response")); });
  expect(await screen.findByRole("alert")).toHaveTextContent(/not confirmed|not inferred|No mutation success/);
  expect(screen.getByText(new RegExp(`Lease: ${leaseId}`))).toBeVisible();
  expect(screen.queryByText(/Release confirmed by exact readback/)).not.toBeInTheDocument();
  expect(failures).toEqual([]);
  handlers.set(`DELETE ${base}/leases/${leaseId}`, () => { handlers.set(`GET ${base}/leases/${leaseId}`, missing); return reply({ released: true }); });
  fireEvent.click(screen.getByRole("button", { name: "Release exact lease" }));
  expect(await screen.findByText(/Release confirmed by exact readback/)).toBeVisible();
});
