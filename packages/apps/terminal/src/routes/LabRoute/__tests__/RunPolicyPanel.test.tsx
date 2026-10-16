import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Activity } from "react";
import { act, fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { ForwardTestSection } from "../ForwardTest";
import { proposalSelector } from "@/services/runPolicy";

const scope = { run_id: "r29-run", actor: "operator", account: "paper:run:r29-run", environment: "paper" };
const row = { ...scope, kind: "practice", config: {}, generation: 1, entries_armed: true, state: "running", uncertain: false,
  protection: "unverified", native_ready: false, books: { positions: [], orders: [], trades: [], pnl: {} } };
const provenance = "operator-supplied-not-measured-entitlement";
const selection = { connection_id: "00000000-0000-4000-8000-000000000041", connection_revision: '"opaque-revision"', model: "synthetic-model", effort: "balanced" };
const dimensions = ["requests", "input_tokens", "output_tokens", "currency_micros", "credits_micros", "compute_milliseconds", "bytes", "concurrency", "storage_bytes"];
const reservation = Object.fromEntries(dimensions.map(key => [key, 1]));
const controls = Object.fromEntries(dimensions.map(key => [key, "hard-local"]));
const sourceFields = ["symbol", "exchange", "action", "entry_price", "exit_price", "quantity", "pnl", "pnl_pct", "exit_reason", "exit_price_estimated", "timestamp"];
const cases = [
  { workflow: "revoke-grant", action: "revoke-grant", value: { role: "reasoning" }, inputs: {} },
  { workflow: "evaluation", action: "evaluation", value: { trial: "synthetic-trial", suite: "synthetic-suite" }, inputs: { trial: "synthetic-trial", suite: "synthetic-suite" } },
  { workflow: "candidate", action: "candidate", value: { candidate: "synthetic-trial", selection, role: "reasoning", identity_scope: "provider-reported-revision", valid_until: 2000000000, deadline_ms: 2000, max_output_tokens: 200, readiness_ttl_seconds: 60 }, inputs: { candidate: "synthetic-trial", "selection.connection_id": selection.connection_id, "selection.connection_revision": selection.connection_revision, "selection.model": selection.model, "selection.effort": selection.effort, valid_until: "2000000000", deadline_ms: "2000", max_output_tokens: "200", readiness_ttl_seconds: "60" } },
  ...["source", "output"].map(subject => ({ workflow: `rights-${subject}`, action: "learning-rights", value: { subject, selection, rights: { grants: [] }, documents: { doc: "Reviewed synthetic document" }, fields: sourceFields, review_statement: "I reviewed these exact bytes and limits" }, inputs: { "selection.connection_id": selection.connection_id, "selection.connection_revision": selection.connection_revision, "selection.model": selection.model, "selection.effort": selection.effort, rights: '{"grants":[]}', documents: '{"doc":"Reviewed synthetic document"}', review_statement: "I reviewed these exact bytes and limits" } })),
  { workflow: "learning-dataset", action: "learning-dataset", value: { source_rights: "event-source", output_rights: "event-output", as_of_start: "2030-01-01T00:00:00Z", as_of_end: "2030-02-01T00:00:00Z" }, inputs: { source_rights: "event-source", output_rights: "event-output", as_of_start: "2030-01-01T00:00:00Z", as_of_end: "2030-02-01T00:00:00Z" } },
  { workflow: "learning-policy", action: "learning-policy", value: { selection, reservation, controls, controls_evidence: "Explicit hard bounds", principal: "synthetic-principal", region: "synthetic-region", terms_revision: "synthetic-terms", valid_until: 2000000000, max_output_tokens: 1, timeout_seconds: 30 }, inputs: { "selection.connection_id": selection.connection_id, "selection.connection_revision": selection.connection_revision, "selection.model": selection.model, "selection.effort": selection.effort, ...Object.fromEntries(dimensions.flatMap(key => [[`reservation.${key}`, "1"], [`controls.${key}`, "hard-local"]])), controls_evidence: "Explicit hard bounds", principal: "synthetic-principal", region: "synthetic-region", terms_revision: "synthetic-terms", valid_until: "2000000000", max_output_tokens: "1", timeout_seconds: "30" } },
  { workflow: "learning-binding", action: "learning-binding", value: { grant_id: "exact-existing-grant" }, inputs: { grant_id: "exact-existing-grant" } },
  { workflow: "training-backend", action: "training-backend", value: { connection_id: "00000000-0000-4000-8000-000000000041", policy: { synthetic: "bounded-policy-test-only" } }, inputs: { connection_id: "00000000-0000-4000-8000-000000000041", policy: '{"synthetic":"bounded-policy-test-only"}' } },
];
function exactRead(url: string) {
  const selector = Object.fromEntries(new URL(url, "http://localhost").searchParams);
  const identity = selector.action === "learning-rights" ? null
    : selector.action === "training-backend" ? { connection_id: selector.connection_id, connection_revision: selection.connection_revision }
      : { trial: selector.trial, experiment_id: "synthetic-experiment", manifest_digest: "a".repeat(64), ...(selector.action === "candidate" ? { evidence_digest: "b".repeat(64), serving_identity: "provider-reported-revision:" + "d".repeat(64) } : { suite_digest: "c".repeat(64) }) };
  return { scope, policy_provenance: provenance, exact_control: { selector, revision: 0, value: null, identity } };
}
function configuration(revision = 0, value: unknown = null) {
  return { scope, policy_provenance: provenance, controls: { access: { revision, value }, "grant:reasoning": { revision: 0, value: null },
    "learning-dataset": { revision: 0, value: null }, "learning-policy": { revision: 0, value: null }, "learning-binding": { revision: 0, value: null } } };
}
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const base = "/v1/model-runs/r29-run/configuration";
beforeEach(() => {
  useAuthStore.setState({ status: "logged-in", token: "synthetic-r29", username: "operator", sessionGeneration: 290 });
  useModeStore.setState({ mode: "live" });
  useBrokerStore.setState({ activeAccountId: "unrelated-live-account" });
});
afterEach(() => vi.unstubAllGlobals());
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><ForwardTestSection /></QueryClientProvider>);
}

it.each(["token", "backend"])("retires visible policy drafts and confirmations on %s replacement", async kind => {
  useConnectionStore.setState({ status: "disconnected" });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/execution-sessions") ? response({ status: "success", data: [row] }) : response(configuration())));
  mount(); fireEvent.click(await screen.findByRole("button", { name: "Configure run policy" })); await screen.findByText(/Authoritative scope/);
  fireEvent.change(screen.getByLabelText("Policy evidence"), { target: { value: "PRIVATE-RETIRED" } });
  act(() => { if (kind === "token") useAuthStore.setState({ token: "synthetic-replacement" }); else useConnectionStore.setState({ status: "connected" }); });
  await waitFor(() => expect(screen.getByLabelText("Policy evidence")).toHaveValue(""));
  expect(screen.queryByText("PRIVATE-RETIRED")).not.toBeInTheDocument();
});

it("clears documents across Activity hide and reconnects a new read-only generation without controls", async () => {
  const posts: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") posts.push(url);
    return url.endsWith("/execution-sessions") ? response({ status: "success", data: [row] }) : response(configuration());
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = (mode: "visible" | "hidden") => <QueryClientProvider client={client}><Activity mode={mode}><ForwardTestSection /></Activity></QueryClientProvider>;
  const view = render(tree("visible"));
  fireEvent.click(await screen.findByRole("button", { name: "Configure run policy" })); await screen.findByText(/Authoritative scope/);
  fireEvent.change(screen.getByLabelText("Policy evidence"), { target: { value: "PRIVATE-HIDDEN" } });
  view.rerender(tree("hidden")); view.rerender(tree("visible"));
  await waitFor(() => expect(screen.getByLabelText("Policy evidence")).toHaveValue(""));
  expect(posts).toEqual([]);
});

it("mounts policy from an actual run and confirms captured access with exact readback without changing Terminal", async () => {
  let revision = 0; let stored: unknown = null;
  const calls: { path: string; method: string | undefined; body: unknown }[] = [];
  const failures: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace(/^\/ft-api/, "");
    const body: unknown = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ path, method: init?.method, body });
    if (path === "/api/v1/execution-sessions") return response({ status: "success", data: [row] });
    if (path === base && init?.method === "GET") return response(configuration(revision, stored));
    if (path === `${base}/preview`) return response({ scope, proposal: body, policy_provenance: provenance, confirmation: "one-use-test-token", expires_in_seconds: 120 });
    if (path === `${base}/confirm`) {
      const exact = { action: "access", expected_revision: 0, value: { operations: ["evaluation.read"], valid_until: 2000000000, evidence: "Operator test policy" }, confirmation: "one-use-test-token" };
      expect(body).toEqual(exact); revision = 1; stored = { ...exact.value, actor: scope.actor };
      return response({ ...configuration(revision, stored), result: null });
    }
    failures.push(`${init?.method} ${path}`); throw new Error("Unregistered transport");
  }));
  mount();
  const run = await screen.findByRole("region", { name: "Practice run r29-run" });
  fireEvent.click(within(run).getByRole("button", { name: "Configure run policy" }));
  const policy = await screen.findByRole("region", { name: "Run policy r29-run" });
  await screen.findByText(/Authoritative scope/);
  fireEvent.click(within(policy).getByRole("checkbox", { name: "evaluation.read" }));
  fireEvent.change(within(policy).getByLabelText("Valid until (epoch seconds)"), { target: { value: "2000000000" } });
  fireEvent.change(within(policy).getByLabelText("Policy evidence"), { target: { value: "Operator test policy" } });
  await act(async () => fireEvent.click(within(policy).getByRole("button", { name: "Preview policy" })));
  expect(within(policy).getByText(/not activation or qualification/i)).toBeVisible();
  await act(async () => fireEvent.click(within(policy).getByRole("button", { name: "Confirm exact policy" })));
  expect(await within(policy).findByText(/Policy verified by exact readback/)).toBeVisible();
  expect(calls.filter(call => call.path.startsWith(base)).map(call => [call.method, call.path])).toEqual([
    ["GET", base], ["POST", `${base}/preview`], ["POST", `${base}/confirm`], ["GET", base],
  ]);
  expect(useModeStore.getState().mode).toBe("live");
  expect(useBrokerStore.getState().activeAccountId).toBe("unrelated-live-account");
  expect(failures).toEqual([]);
});

it.each(cases)("serialises the mounted $workflow proposal without adding authority or numeric defaults", async testCase => {
  const posts: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/execution-sessions")) return response({ status: "success", data: [row] });
    if (url.includes("/control?")) return response(exactRead(url));
    if (url.endsWith("/preview")) {
      const proposal = JSON.parse(String(init?.body)); posts.push(proposal);
      const selector = proposalSelector(proposal);
      const target_identity = selector ? exactRead("/control?" + new URLSearchParams(selector)).exact_control.identity : undefined;
      return response({ scope, proposal, target_identity, policy_provenance: provenance, confirmation: "test-preview-only", expires_in_seconds: 120 });
    }
    return response(configuration());
  }));
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Configure run policy" }));
  await screen.findByText(/Authoritative scope/);
  fireEvent.change(screen.getByLabelText("Policy workflow"), { target: { value: testCase.workflow } });
  for (const [name, value] of Object.entries(testCase.inputs)) {
    const field = document.querySelector(`[name="${name}"]`);
    expect(field, `mounted field ${name}`).not.toBeNull();
    fireEvent.change(field!, { target: { value } });
  }
  const read = screen.queryByRole("button", { name: "Read selected control" });
  if (read) { fireEvent.click(read); await screen.findByText(/Current control revision: 0/); }
  fireEvent.click(screen.getByRole("button", { name: "Preview policy" }));
  await screen.findByRole("button", { name: "Confirm exact policy" });
  expect(posts).toEqual([{ action: testCase.action, expected_revision: 0, value: testCase.value }]);
});

it("presents reasoning grant separately from activation and cancels a preview when its draft changes", async () => {
  const posts: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/execution-sessions")) return response({ status: "success", data: [row] });
    if (url.endsWith("/preview")) {
      const proposal: unknown = JSON.parse(String(init?.body)); posts.push(proposal);
      return response({ scope, proposal, policy_provenance: provenance, confirmation: "grant-preview", expires_in_seconds: 120 });
    }
    return response(configuration());
  }));
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Configure run policy" }));
  await screen.findByText(/Authoritative scope/);
  fireEvent.change(screen.getByLabelText("Policy workflow"), { target: { value: "grant" } });
  fireEvent.change(screen.getByLabelText("Valid until (epoch seconds)"), { target: { value: "2000000000" } });
  fireEvent.change(screen.getByLabelText("Policy evidence"), { target: { value: "Exact reasoning role" } });
  fireEvent.click(screen.getByRole("button", { name: "Preview policy" }));
  await screen.findByRole("button", { name: "Confirm exact policy" });
  expect(posts).toEqual([{ action: "grant", expected_revision: 0, value: { role: "reasoning", identity_scope: "provider-reported-revision", valid_until: 2000000000, evidence: "Exact reasoning role" } }]);
  fireEvent.change(screen.getByLabelText("Policy evidence"), { target: { value: "Edited after preview" } });
  expect(screen.queryByRole("button", { name: "Confirm exact policy" })).not.toBeInTheDocument();
});

it("retires the stale configuration display when an explicit read is refused", async () => {
  let reads = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/execution-sessions") ? response({ status: "success", data: [row] }) : reads++ ? response({ code: "unavailable" }, 503) : response(configuration())));
  mount(); fireEvent.click(await screen.findByRole("button", { name: "Configure run policy" })); await screen.findByText(/Authoritative scope/);
  fireEvent.click(screen.getByRole("button", { name: "Read exact policy" }));
  await screen.findByRole("alert");
  expect(screen.queryByText(/Authoritative scope/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Preview policy" })).not.toBeInTheDocument();
});

it("labels canonical rights ACK as unverified when current API omits the exact control readback", async () => {
  let exactReads = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/execution-sessions")) return response({ status: "success", data: [row] });
    if (url.endsWith("/preview")) return response({ scope, proposal: JSON.parse(String(init?.body)), policy_provenance: provenance, confirmation: "rights-once", expires_in_seconds: 120 });
    if (url.endsWith("/confirm")) return response({ ...configuration(), result: { event_id: "canonical-source-event-from-ACK", rights_digest: "synthetic-digest", policy_provenance: "operator-reviewed-document-evidence" } });
    if (url.includes("/control?") && exactReads++ === 0) return response(exactRead(url));
    return response(configuration());
  }));
  mount(); fireEvent.click(await screen.findByRole("button", { name: "Configure run policy" })); await screen.findByText(/Authoritative scope/);
  const testCase = cases.find(value => value.workflow === "rights-source")!;
  fireEvent.change(screen.getByLabelText("Policy workflow"), { target: { value: testCase.workflow } });
  for (const [name, value] of Object.entries(testCase.inputs)) fireEvent.change(document.querySelector(`[name="${name}"]`)!, { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Read selected control" }));
  await screen.findByText(/Current control revision: 0/);
  fireEvent.click(screen.getByRole("button", { name: "Preview policy" }));
  fireEvent.click(await screen.findByRole("button", { name: "Confirm exact policy" }));
  expect(await screen.findByText(/Acknowledged only — exact control readback unavailable/)).toBeVisible();
  expect(screen.getByText("canonical-source-event-from-ACK")).toBeVisible();
  expect(screen.queryByText(/Policy verified by exact readback/)).not.toBeInTheDocument();
});

it("keeps private rights documents local to the current visible view and suppresses late preview", async () => {
  let release!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/execution-sessions")) return response({ status: "success", data: [row] });
    if (url.endsWith("/preview")) return new Promise<Response>(resolve => { release = resolve; });
    return response(configuration());
  }));
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Configure run policy" }));
  await screen.findByText(/Authoritative scope/);
  fireEvent.change(screen.getByLabelText("Policy workflow"), { target: { value: "rights-source" } });
  expect(screen.getByText(/not a legal determination/i)).toBeVisible();
  const documents = screen.getByLabelText("Reviewed documents (fact ID to UTF-8 text JSON)");
  fireEvent.change(documents, { target: { value: '{"source":"PRIVATE-DOCUMENT-R29"}' } });
  fireEvent.click(screen.getByRole("button", { name: "Hide run policy" }));
  fireEvent.click(screen.getByRole("button", { name: "Configure run policy" }));
  await screen.findByText(/Authoritative scope/);
  fireEvent.change(screen.getByLabelText("Policy workflow"), { target: { value: "rights-source" } });
  expect(screen.getByLabelText("Reviewed documents (fact ID to UTF-8 text JSON)")).toHaveValue("");
  expect(JSON.stringify(localStorage)).not.toContain("PRIVATE-DOCUMENT-R29");
  fireEvent.change(screen.getByLabelText("Policy workflow"), { target: { value: "grant" } });
  fireEvent.change(screen.getByLabelText("Valid until (epoch seconds)"), { target: { value: "2000000000" } });
  fireEvent.change(screen.getByLabelText("Policy evidence"), { target: { value: "Late private grant" } });
  fireEvent.click(screen.getByRole("button", { name: "Preview policy" }));
  await waitFor(() => expect(release).toBeTypeOf("function"));
  fireEvent.click(screen.getByRole("button", { name: "Hide run policy" }));
  await act(async () => release(response({ scope, policy_provenance: provenance, proposal: {}, confirmation: "late", expires_in_seconds: 120 })));
  expect(screen.queryByText(/Late private grant/)).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
