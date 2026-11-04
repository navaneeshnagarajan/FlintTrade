import { Activity } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { ForwardTestSection } from "../ForwardTest";
import fixture from "@/services/__tests__/fixtures/executionSessions.synthetic.json";
import retirement from "@/services/__tests__/fixtures/executionSessions.retirement.synthetic.json";
import cancellation from "@/services/__tests__/fixtures/executionSessions.cancel.synthetic.json";
import stale from "@/services/__tests__/fixtures/executionSessions.stale.synthetic.json";

let generation = 1500;
beforeEach(() => {
  useAuthStore.setState({ status: "logged-in", token: "synthetic-native-panel", username: "synthetic-operator", sessionGeneration: ++generation });
  useModeStore.setState({ mode: "live" });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("retains the literal Native Live refusal beside inspection and entry-retirement guidance", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`; calls.push(key);
    if (key !== "GET /api/v1/execution-sessions") throw new Error(`Unregistered ${key}`);
    return new Response(JSON.stringify({ status: "success", data: [] }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const mounted = render(<QueryClientProvider client={client}><ForwardTestSection /></QueryClientProvider>);
  try {
    await screen.findByText(/No registered runs/);
    const panel = screen.getByRole("region", { name: "Execution sessions" });
    expect(within(panel).getByText("Native Live execution remains unavailable.", { exact: false })).toBeVisible();
    expect(within(panel).getByText("Inspection and entry retirement are available here; activation, qualification and protection controls are unavailable.", { exact: false })).toBeVisible();
    expect(within(panel).getByText("Runs belong to the backend and continue across app switches and UI closure. Logout retires entries; restart requires reconciliation.", { exact: false })).toBeVisible();
    expect(calls).toEqual(["GET /api/v1/execution-sessions"]);
  } finally {
    mounted.unmount(); client.clear();
  }
});

it.each(Object.entries(retirement.scenarios))("allows canonical retirement of a retained %s-blocked grant while entries and native controls stay denied", async (_name, responses) => {
  const calls: string[] = []; const failures: unknown[] = [];
  let stopped = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`; calls.push(key);
    try {
      expect(Object.fromEntries(new Headers(init?.headers))).toEqual(init?.method === "POST"
        ? { authorization: "Bearer synthetic-native-panel", "content-type": "application/json" }
        : { authorization: "Bearer synthetic-native-panel" });
      if (key === "GET /api/v1/execution-sessions") return new Response(JSON.stringify({ status: "success", data: [stopped ? responses.stopped.data : responses.blocked.data] }));
      if (key === "POST /api/v1/execution-sessions/bounded-one/stop") {
        expect(JSON.parse(String(init?.body))).toEqual({ account: "dhan:inert-account", environment: "live", expected_generation: 0 });
        stopped = true; return new Response(JSON.stringify(responses.stopAck));
      }
      if (key === "GET /api/v1/execution-sessions/bounded-one") return new Response(JSON.stringify(responses.stopped));
      throw new Error(`Unregistered ${key}`);
    } catch (error) { failures.push(error); throw error; }
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const mounted = render(<QueryClientProvider client={client}><ForwardTestSection /></QueryClientProvider>);
  const region = await screen.findByRole("region", { name: "Live run bounded-one" });
  expect(within(region).getByText(/Effective entry authority: not authorised/)).toBeVisible();
  expect(within(region).getByText(/Native readiness reported by Core: not ready/)).toBeVisible();
  expect(within(region).getByText(/Grant grant-one: not marked revoked/)).toBeVisible();
  const stop = within(region).getByRole("button", { name: "Stop entries" });
  expect(stop).toBeEnabled();
  for (const name of [/Configure run policy/, /Protection policy/, /Close run positions/, /Start exact run/, /Rearm exact run/]) {
    expect(within(region).queryByRole("button", { name })).not.toBeInTheDocument();
  }
  fireEvent.click(stop);
  await waitFor(() => expect(within(region).getByText(/Grant grant-one: revoked/)).toBeVisible());
  expect(stop).toBeDisabled();
  expect(within(region).getByText(/Effective entry authority: not authorised/)).toBeVisible();
  expect(within(region).getByText(/Native readiness reported by Core: not ready/)).toBeVisible();
  expect(within(region).getByText(/not proof of broker flatness/)).toBeVisible();
  fireEvent.click(stop);
  expect(calls).toEqual(["GET /api/v1/execution-sessions", "POST /api/v1/execution-sessions/bounded-one/stop", "GET /api/v1/execution-sessions/bounded-one", "GET /api/v1/execution-sessions"]);
  expect(useModeStore.getState().mode).toBe("live");
  mounted.unmount(); client.clear(); expect(failures).toEqual([]);
});

it.each([
  ["configured without grant", fixture.responses.configured.data],
  ["qualified without grant", retirement.controls.qualifiedWithoutGrant.data],
  ["already revoked", fixture.responses.stopped.data],
  ["restart retired grant", stale.responses.restart.data],
  ["legacy without projection", fixture.responses.mixed.data[1]],
])("keeps native Stop disabled for %s", async (_name, row) => {
  const calls: string[] = []; const failures: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`; calls.push(key);
    try {
      expect(key).toBe("GET /api/v1/execution-sessions");
      expect(Object.fromEntries(new Headers(init?.headers))).toEqual({ authorization: "Bearer synthetic-native-panel" });
      return new Response(JSON.stringify({ status: "success", data: [row] }));
    } catch (error) { failures.push(error); throw error; }
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const mounted = render(<QueryClientProvider client={client}><ForwardTestSection /></QueryClientProvider>);
  const region = await screen.findByRole("region", { name: `Live run ${row.run_id}` });
  const stop = within(region).getByRole("button", { name: "Stop entries" });
  expect(stop).toBeDisabled(); fireEvent.click(stop);
  expect(calls).toEqual(["GET /api/v1/execution-sessions"]);
  mounted.unmount(); client.clear(); expect(failures).toEqual([]);
});

it("inspects native receipts separately from Paper and retires effective authority even when outer entries are false", async () => {
  const calls: string[] = []; const failures: unknown[] = [];
  let stopped = false;
  const legacy = fixture.responses.mixed.data[1];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`; calls.push(key);
    try {
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer synthetic-native-panel");
      expect(headers.get("X-FlintTrade-Mode")).toBeNull();
      expect(headers.get("X-FlintTrade-Account")).toBeNull();
      expect(headers.get("X-Broker-Account")).toBeNull();
      if (key === "GET /api/v1/execution-sessions") return new Response(JSON.stringify({ status: "success", data: [fixture.responses.paper.data, legacy, stopped ? fixture.responses.stopped.data : fixture.responses.partial.data] }));
      if (key === "POST /api/v1/execution-sessions/bounded-one/stop") {
        expect(JSON.parse(String(init?.body))).toEqual({ account: "dhan:inert-account", environment: "live", expected_generation: 0 });
        stopped = true; return new Response(JSON.stringify(fixture.responses.stopAck));
      }
      if (key === "GET /api/v1/execution-sessions/bounded-one") return new Response(JSON.stringify(fixture.responses.stopped));
      throw new Error(`Unregistered ${key}`);
    } catch (error) { failures.push(error); throw error; }
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = (hidden: boolean) => <QueryClientProvider client={client}><Activity mode={hidden ? "hidden" : "visible"}><ForwardTestSection /></Activity></QueryClientProvider>;
  const mounted = render(view(false));
  const native = await screen.findByRole("region", { name: "Live run bounded-one" });
  expect(within(native).getByText(/Effective entry authority: authorised/)).toBeVisible();
  expect(within(native).getByText(/Requested authority: place/)).toBeVisible();
  expect(within(native).getByText(/reconciliation_required/)).toBeVisible();
  expect(within(native).getByText(/Grant expiry/)).toBeVisible();
  expect(within(native).getByText(/Qualification expiry/)).toBeVisible();
  expect(within(native).getByRole("list", { name: "Unresolved obligations" })).toHaveTextContent("command-one");
  expect(within(native).getByRole("list", { name: "Command receipts" })).toHaveTextContent("partial");
  expect(within(native).getByRole("list", { name: "Command receipts" })).toHaveTextContent("observed filled quantity: 1");
  expect(within(native).queryByText(/Entries retired/)).not.toBeInTheDocument();
  for (const name of [/Configure run policy/, /Protection policy/, /Close run positions/, /Start exact run/, /Rearm exact run/]) {
    expect(within(native).queryByRole("button", { name })).not.toBeInTheDocument();
  }
  const paper = screen.getByRole("region", { name: "Practice run paper-synthetic" });
  expect(within(paper).getByRole("button", { name: "Configure run policy" })).toBeVisible();
  expect(within(paper).getByRole("button", { name: "Protection policy" })).toBeVisible();
  expect(within(paper).getByRole("button", { name: "Close run positions…" })).toBeVisible();
  expect(within(screen.getByRole("region", { name: "Live run legacy-synthetic" })).getByText(/Native authority unavailable/)).toBeVisible();
  act(() => useModeStore.setState({ mode: "practice" }));
  mounted.rerender(view(true)); mounted.rerender(view(false));
  expect(calls.filter(c => c.startsWith("POST"))).toEqual([]);
  fireEvent.click(within(native).getByRole("button", { name: "Stop entries" }));
  await waitFor(() => expect(within(native).getByText(/Effective entry authority: not authorised/)).toBeVisible());
  expect(within(native).getByRole("button", { name: "Stop entries" })).toBeDisabled();
  expect(within(native).getByRole("list", { name: "Unresolved obligations" })).toHaveTextContent("command-one");
  expect(within(native).getByText(/not proof of broker flatness/)).toBeVisible();
  expect(calls.filter(c => c.startsWith("POST"))).toEqual(["POST /api/v1/execution-sessions/bounded-one/stop"]);
  expect(calls.filter(c => c === "GET /api/v1/execution-sessions/bounded-one")).toHaveLength(1);
  expect(useModeStore.getState().mode).toBe("practice");
  mounted.unmount(); expect(calls.filter(c => c.startsWith("POST"))).toHaveLength(1);
  expect(failures).toEqual([]);
});

it("refuses the whole cancellation census rather than displaying fills against a contradictory expected order", async () => {
  // Explicit fabricated negative: two-unit placement, contradictory expected 200,
  // and 100 claimed fills. None of these alterations is producer evidence.
  const broken = structuredClone(cancellation.responses.cancelRequested.data);
  const cancel = broken.autonomy.commands.find(command => command.operation === "cancel")!;
  cancel.expected_order!.quantity = 200;
  Object.assign(cancel, { filled_quantity: 100 });
  const calls: string[] = []; const failures: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`; calls.push(key);
    try {
      expect(key).toBe("GET /api/v1/execution-sessions");
      expect(Object.fromEntries(new Headers(init?.headers))).toEqual({ authorization: "Bearer synthetic-native-panel" });
      return new Response(JSON.stringify({ status: "success", data: [fixture.responses.paper.data, broken] }));
    } catch (error) { failures.push(error); throw error; }
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const mounted = render(<QueryClientProvider client={client}><ForwardTestSection /></QueryClientProvider>);
  expect(await screen.findByRole("alert")).toHaveTextContent("Run census unavailable");
  expect(screen.queryByRole("region", { name: "Live run bounded-one" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Practice run paper-synthetic" })).not.toBeInTheDocument();
  expect(screen.queryByText(/observed filled quantity: 100/)).not.toBeInTheDocument();
  expect(screen.queryByText(/No registered runs/)).not.toBeInTheDocument();
  expect(calls).toEqual(["GET /api/v1/execution-sessions"]);
  mounted.unmount(); client.clear(); expect(failures).toEqual([]);
});

it("displays a finite Core qualification expiry outside the browser date range without losing the census", async () => {
  const native = fixture.responses.ready.data;
  const longExpiry = { ...native, autonomy: { ...native.autonomy,
    qualification: { ...native.autonomy.qualification, expires_at: 1e300 },
    grant: { ...native.autonomy.grant, qualification: { ...native.autonomy.grant.qualification, expires_at: 1e300 } },
  } };
  const failures: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`;
    if (key !== "GET /api/v1/execution-sessions") { failures.push(key); throw new Error(key); }
    return new Response(JSON.stringify({ status: "success", data: [longExpiry] }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><ForwardTestSection /></QueryClientProvider>);
  const region = await screen.findByRole("region", { name: "Live run bounded-one" });
  expect(within(region).getByText(/Qualification expiry: 1e\+300 epoch seconds/)).toBeVisible();
  expect(failures).toEqual([]);
});

it("keeps known fills and obligations visible beside a synthetic late ACK observation", async () => {
  // Deliberate boundary alteration of the captured serializer response, not a
  // purported sample from the fixed Core finalisation path.
  const native = fixture.responses.partial.data;
  const lateAck = { ...native, autonomy: { ...native.autonomy,
    commands: native.autonomy.commands.map(c => ({ ...c, state: "acknowledged", events: [...c.events, "acknowledged"] })),
  } };
  const calls: string[] = []; const failures: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`; calls.push(key);
    if (key !== "GET /api/v1/execution-sessions") { failures.push(key); throw new Error(key); }
    return new Response(JSON.stringify({ status: "success", data: [lateAck] }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><ForwardTestSection /></QueryClientProvider>);
  const region = await screen.findByRole("region", { name: "Live run bounded-one" });
  expect(within(region).getByRole("list", { name: "Command receipts" })).toHaveTextContent("acknowledged");
  expect(within(region).getByRole("list", { name: "Command receipts" })).toHaveTextContent("observed filled quantity: 1");
  expect(within(region).getByRole("list", { name: "Unresolved obligations" })).toHaveTextContent("command-one");
  expect(within(region).getByText(/Native readiness reported by Core: not ready/)).toBeVisible();
  expect(within(region).getByText(/not proof of broker flatness/)).toBeVisible();
  expect(calls).toEqual(["GET /api/v1/execution-sessions"]); expect(failures).toEqual([]);
});

it("withdraws the entire visible census after an invalid native row instead of showing a healthy Paper subset", async () => {
  let reads = 0;
  const calls: string[] = []; const failures: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`; calls.push(key);
    if (key !== "GET /api/v1/execution-sessions") { failures.push(key); throw new Error(key); }
    const native = ++reads === 1 ? fixture.responses.ready.data
      : { ...fixture.responses.ready.data, autonomy: { ...fixture.responses.ready.data.autonomy, authorised: false } };
    return new Response(JSON.stringify({ status: "success", data: [fixture.responses.paper.data, native] }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><ForwardTestSection /></QueryClientProvider>);
  await screen.findByRole("region", { name: "Live run bounded-one" });
  fireEvent.click(screen.getByRole("button", { name: "Refresh runs" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Run census unavailable");
  expect(screen.queryByRole("region", { name: "Live run bounded-one" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Practice run paper-synthetic" })).not.toBeInTheDocument();
  expect(screen.queryByText(/No registered runs/)).not.toBeInTheDocument();
  expect(calls).toEqual(["GET /api/v1/execution-sessions", "GET /api/v1/execution-sessions"]);
  expect(failures).toEqual([]);
});

it("does not publish a late native Stop into a replacement operator session", async () => {
  let release: ((value: Response) => void) | undefined;
  let entered: (() => void) | undefined;
  const readEntered = new Promise<void>(resolve => { entered = resolve; });
  const calls: string[] = []; const failures: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const bearer = new Headers(init?.headers).get("Authorization");
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")} ${bearer}`; calls.push(key);
    if (key === "GET /api/v1/execution-sessions Bearer synthetic-native-panel") return new Response(JSON.stringify({ status: "success", data: [fixture.responses.partial.data] }));
    if (key === "POST /api/v1/execution-sessions/bounded-one/stop Bearer synthetic-native-panel") return new Response(JSON.stringify(fixture.responses.stopAck));
    if (key === "GET /api/v1/execution-sessions/bounded-one Bearer synthetic-native-panel") {
      const held = new Promise<Response>(resolve => { release = resolve; }); entered?.(); return await held;
    }
    if (key === "GET /api/v1/execution-sessions Bearer synthetic-replacement") return new Response(JSON.stringify({ status: "success", data: [] }));
    failures.push(key); throw new Error(key);
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><ForwardTestSection /></QueryClientProvider>);
  const native = await screen.findByRole("region", { name: "Live run bounded-one" });
  await act(async () => { fireEvent.click(within(native).getByRole("button", { name: "Stop entries" })); await readEntered; });
  act(() => useAuthStore.setState({ token: "synthetic-replacement", sessionGeneration: ++generation }));
  await screen.findByText(/No registered runs/);
  await act(async () => { release?.(new Response(JSON.stringify(fixture.responses.stopped))); });
  expect(screen.queryByRole("region", { name: "Live run bounded-one" })).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByText(/Pending exact run/)).not.toBeInTheDocument();
  expect(calls.filter(c => c.startsWith("POST"))).toHaveLength(1);
  expect(calls.filter(c => c.endsWith("Bearer synthetic-replacement"))).toEqual(["GET /api/v1/execution-sessions Bearer synthetic-replacement"]);
  expect(failures).toEqual([]);
});
