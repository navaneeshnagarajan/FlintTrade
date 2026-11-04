import legacy from "@/services/__tests__/fixtures/executionSessions.synthetic.json";
import { StrictMode } from "react";
import fixture from "@/services/__tests__/fixtures/native-v2-captured-v2.json";
import { QueryClient, QueryClientProvider, onlineManager } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { ExecutionSessionsPanel } from "../ExecutionSessionsPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); onlineManager.setOnline(true); });

it("mounts a readonly native configuration with blank limits and no requests or unavailable financial actions", () => {
  useAuthStore.setState({ status: "logged-out", token: null, username: null, sessionGeneration: 9100 });
  useBrokerStore.setState({ accounts: [], activeAccountId: null });
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const mounted = render(<QueryClientProvider client={client}><ExecutionSessionsPanel /></QueryClientProvider>);
  expect(screen.getByRole("heading", { name: "Native Studio" })).toBeVisible();
  for (const label of ["Capital cap", "Exposure cap", "Loss action threshold", "Maximum mark age (ms)"]) {
    expect(screen.getByLabelText(label)).toHaveValue("");
  }
  expect(screen.getByRole("button", { name: "Save native configuration" })).toBeDisabled();
  for (const name of [/^Grant/, /^Start native/, /^Accept transfer/]) {
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
  expect(fetcher).not.toHaveBeenCalled();
  mounted.unmount(); client.clear();
});

let generation = 9200;
function authenticate() {
  const account = { account_id: "Mounted", broker: "dhan", source: "native" as const,
    label: "Synthetic inert account", status: "connected" as const, is_primary: true,
    connected_at: null, error_message: null };
  useAuthStore.setState({ status: "logged-in", token: "synthetic-studio-ui", username: "mounted-operator",
    sessionGeneration: ++generation });
  useBrokerStore.setState({ accounts: [account], activeAccountId: brokerAccountKey(account) });
  return account;
}

it.each(["late success", "late error"])("detaches the previous account's draft, evidence and %s at the switch", async outcome => {
  const account = authenticate();
  const samples = fixture.samples.filter(row => row.case.endsWith("test_normal_factory_mounts_versioned_configuration_without_authority"));
  const census = samples.find(row => row.path.endsWith("/execution-sessions"))!;
  const read = samples.find(row => row.path.endsWith("/autonomy-v2"))!;
  let release: ((response: Response) => void) | undefined;
  let reject: ((error: Error) => void) | undefined;
  let signal: AbortSignal | null | undefined;
  const calls: string[] = []; const failures: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace(/^\/ft-api/, ""); calls.push(`${init?.method} ${path}`);
    if (path === census.path) return new Response(census.body);
    if (path === read.path) {
      signal = init?.signal;
      return new Promise<Response>((yes, no) => { release = yes; reject = no; });
    }
    failures.push(path); throw new Error(`Unregistered ${path}`);
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const mounted = render(<StrictMode><QueryClientProvider client={client}><ExecutionSessionsPanel /></QueryClientProvider></StrictMode>);
  let studio = screen.getByRole("region", { name: "Native Studio" });
  fireEvent.change(within(studio).getByLabelText("Capital cap"), { target: { value: "300" } });
  fireEvent.click(await within(studio).findByRole("button", { name: "Inspect mounted-native" }));
  await waitFor(() => expect(release).toBeTypeOf("function"));
  expect(within(studio).getByRole("region", { name: "Native run evidence" })).toBeVisible();
  act(() => {
    const other = { ...account, account_id: "Other" };
    useBrokerStore.setState({ accounts: [account, other], activeAccountId: brokerAccountKey(other) });
  });
  expect(studio).not.toBeInTheDocument();
  studio = screen.getByRole("region", { name: "Native Studio" });
  expect(within(studio).queryByRole("region", { name: "Native run evidence" })).not.toBeInTheDocument();
  expect(within(studio).getByLabelText("Capital cap")).toHaveValue("");
  expect(signal?.aborted).toBe(true);
  await act(async () => {
    if (outcome === "late success") release?.(new Response(read.body));
    else reject?.(new Error("synthetic old-account error"));
  });
  expect(within(studio).queryByRole("alert")).not.toBeInTheDocument();
  expect(within(studio).queryByText(/mounted-native/)).not.toBeInTheDocument();
  expect(calls).toEqual([`GET ${census.path}`, `GET ${read.path}`]);
  expect(failures).toEqual([]);
  mounted.unmount(); client.clear();
});

it("keeps Stop available for stale disconnected account evidence and renders retirement, never flatness", async () => {
  const account = authenticate();
  const samples = fixture.samples.filter(row => row.case.endsWith("test_freshness_is_local_and_stale_account_does_not_block_stop"));
  const exact = "/api/v1/execution-sessions/mounted-native";
  const initial = samples.find(row => row.method === "GET" && row.path === exact)!;
  const stop = samples.find(row => row.method === "POST" && row.path === `${exact}/stop`)!;
  const views = samples.filter(row => row.method === "GET" && row.path === `${exact}/autonomy-v2`);
  const shared = samples.filter(row => row.method === "GET" && row.path === exact);
  const initialCensus = samples.find(row => row.path === "/api/v1/execution-sessions"
    && JSON.parse(row.body).data.some((value: { autonomy_v2: { observation_freshness: string } }) =>
      value.autonomy_v2.observation_freshness === "stale"))!;
  const calls: string[] = []; const failures: unknown[] = [];
  let stopped = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace(/^\/ft-api/, ""); calls.push(`${init?.method} ${path}`);
    try {
      if (path === initialCensus.path) return new Response(initialCensus.body);
      if (init?.method === "POST") {
        expect(path).toBe(`${exact}/stop`);expect(JSON.parse(String(init.body))).toEqual(stop.request_json);
        stopped = true;return new Response(stop.body);
      }
      expect([exact,`${exact}/autonomy-v2`]).toContain(path);
      return new Response(path === exact ? stopped ? shared.at(-1)!.body : initial.body
        : stopped ? views.at(-1)!.body : views[0]!.body);
    } catch (error) { failures.push(error);throw error; }
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const mounted = render(<QueryClientProvider client={client}><ExecutionSessionsPanel /></QueryClientProvider>);
  let studio = screen.getByRole("region", { name: "Native Studio" });
  fireEvent.click(await within(studio).findByRole("button", { name: "Inspect mounted-native" }));
  await within(studio).findByText(/Qualification: blocked/);
  await waitFor(() => expect(within(studio).queryByRole("status")).not.toBeInTheDocument());
  act(() => useBrokerStore.getState().setAccounts([{ ...account, status: "disconnected", read_only: true }]));
  const button = within(studio).getByRole("button", { name: "Stop native entries" });
  expect(button).toBeEnabled();fireEvent.click(button);
  await within(studio).findByText("retired / not_started");
  expect(button).toBeDisabled();
  expect(within(studio).getByText(/not a zero-exposure census/)).toBeVisible();
  expect(within(studio).getByText(/does not cancel exchange orders/)).toBeVisible();
  expect(calls).toEqual([`GET ${initialCensus.path}`,`GET ${exact}/autonomy-v2`,`GET ${exact}`,
    `POST ${exact}/stop`,`GET ${exact}/autonomy-v2`,`GET ${exact}`]);
  expect(failures).toEqual([]);
  act(() => onlineManager.setOnline(false));
  expect(studio).not.toBeInTheDocument();
  studio = screen.getByRole("region", { name: "Native Studio" });
  expect(within(studio).getByText(/Offline —/)).toBeVisible();
  expect(within(studio).queryByRole("region", { name: "Native run evidence" })).not.toBeInTheDocument();
  mounted.unmount();client.clear();
});

it("never places legacy or Paper rows in the native v2 selection when no native account is selected", async () => {
  authenticate(); useBrokerStore.setState({ accounts: [], activeAccountId: null });
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method} ${url.replace(/^\/ft-api/, "")}`);
    return new Response(JSON.stringify(legacy.responses.mixed));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const mounted = render(<QueryClientProvider client={client}><ExecutionSessionsPanel /></QueryClientProvider>);
  await screen.findByRole("region", { name: "Live run bounded-one" });
  const studio = screen.getByRole("region", { name: "Native Studio" });
  expect(within(studio).queryByRole("button", { name: /^Inspect / })).not.toBeInTheDocument();
  expect(calls).toEqual(["GET /api/v1/execution-sessions"]);
  mounted.unmount(); client.clear();
});

it.each(["native:run", "native.run", "native/run", " native", "native ", "a".repeat(129)])(
  "preserves the literal mounted run ID %j and refuses it before an exact read", async id => {
    authenticate();
    const census = fixture.samples.find(row => row.path === "/api/v1/execution-sessions"
      && row.case.endsWith("test_normal_factory_mounts_versioned_configuration_without_authority"))!;
    const failures: unknown[] = []; const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      try {
        expect(url).toBe(`/ft-api${census.path}`); expect(init?.method).toBe("GET");
        expect(init?.body).toBeUndefined(); calls.push(url); return new Response(census.body);
      } catch (error) { failures.push(error); throw error; }
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const mounted = render(<QueryClientProvider client={client}><ExecutionSessionsPanel /></QueryClientProvider>);
    const studio = within(screen.getByRole("region", { name: "Native Studio" }));
    await studio.findByRole("button", { name: "Inspect mounted-native" });
    fireEvent.change(studio.getByLabelText("Exact native run ID"), { target: { value: id } });
    fireEvent.click(studio.getByRole("button", { name: "Read exact native status" }));
    await studio.findByRole("alert");
    expect(studio.getByLabelText("Exact native run ID")).toHaveValue(id);
    expect(calls).toEqual([`/ft-api${census.path}`]); expect(failures).toEqual([]);
    expect(studio.queryByRole("region", { name: "Native run evidence" })).not.toBeInTheDocument();
    mounted.unmount(); client.clear();
  },
);

it.each(["duplicate", "foreign run", "missing collection"])("refuses a %s complete census at the mounted owner", async fault => {
  authenticate();
  const captured = fixture.samples.find(row => row.path === "/api/v1/execution-sessions"
    && row.case.endsWith("test_normal_factory_mounts_versioned_configuration_without_authority"))!;
  const raw = JSON.parse(captured.body);
  if (fault === "duplicate") raw.data.push(structuredClone(raw.data[0]));
  if (fault === "foreign run") raw.data[0].autonomy_v2.scope.run_id = "foreign-owner";
  if (fault === "missing collection") delete raw.data;
  const fetcher = vi.fn(async () => new Response(JSON.stringify(raw))); vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const mounted = render(<QueryClientProvider client={client}><ExecutionSessionsPanel /></QueryClientProvider>);
  await screen.findByText("Run census unavailable — this is not an empty or stopped book.");
  const studio = within(screen.getByRole("region", { name: "Native Studio" }));
  expect(studio.queryByRole("button", { name: "Inspect mounted-native" })).not.toBeInTheDocument();
  expect(studio.queryByRole("region", { name: "Native run evidence" })).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(1); mounted.unmount(); client.clear();
});
