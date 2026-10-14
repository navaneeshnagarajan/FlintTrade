import { createHash, webcrypto } from "node:crypto";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";
import InvestRoute from "@/routes/InvestRoute";

// Retained investment views are neighbours, not the evidence transport.
vi.mock("@/routes/invest/InvestContext", () => ({ InvestProvider: ({ children }: { children: React.ReactNode }) => children, useInvest: () => ({ holdings: [], isLoading: false, isSampleData: false }) }));
vi.mock("@/routes/invest/tabs/DashboardTab", () => ({ DashboardTab: () => <p>Retained investment dashboard</p> }));
vi.mock("@/components/help/SpotlightTour", () => ({ SpotlightTour: () => null }));

const path = "/ft-api/api/v1/data/portfolio/evidence";
const scope = { principal_id: "synthetic-operator", environment: "manual_ledger", account_id: "manual:synthetic-operator", run_id: null, generation: 4 };
const row = { record_id: "declared-1", kind: "holding", instrument_id: "synthetic-fund", venue: "declared-register", currency: "INR", quantity_unit: "units", quantity: "1.250", cash_amount: null, observed_at: "2026-01-02T10:00:00+00:00", source_id: "user-statement", origin: "manual", input_sha256: "a".repeat(64), published_at: null, retrieved_at: "2026-01-02T11:00:00+00:00" };
const evidence = (records: unknown[] = [row]) => ({ scope, records, status: records.length ? "partial" : "unavailable", complete: false, execution_authority: false, holdings_inferred_from_transactions: false });
const reply = (data: unknown, status = 200) => new Response(JSON.stringify({ status: "success", data }), { status });
type Handler = (init: RequestInit) => Response | Promise<Response>;
let handlers: Map<string, Handler>;
let calls: string[];
let failures: unknown[];
let client: QueryClient;

beforeEach(() => {
  vi.stubGlobal("crypto", webcrypto);
  useAuthStore.setState({ status: "logged-in", token: "synthetic-session-A", username: "synthetic-operator", sessionGeneration: 4 });
  useBrokerStore.setState({ activeAccountId: "native:synthetic:A" });
  useConnectionStore.setState({ apiKey: "" });
  useModeStore.setState({ mode: "live" });
  window.history.replaceState(null, "", "/invest");
  handlers = new Map([[`GET ${path}`, () => reply(evidence())]]);
  calls = []; failures = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const key = `${init.method ?? "GET"} ${url}`; calls.push(key);
    try {
      const handler = handlers.get(key);
      expect(handler, `Unregistered transport: ${key}`).toBeDefined();
      expect(init.cache).toBe("no-store");
      expect(new Headers(init.headers).get("Authorization")).toBe("Bearer synthetic-session-A");
      return await handler!(init);
    } catch (error) { failures.push(error); throw error; }
  }));
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
});
afterEach(() => { cleanup(); client.clear(); vi.unstubAllGlobals(); expect(failures).toEqual([]); });
async function mount() {
  await act(async () => { render(<QueryClientProvider client={client}><MemoryRouter><InvestRoute /></MemoryRouter></QueryClientProvider>); await import("@/routes/invest/tabs/DashboardTab"); });
}

it("retains accepted opaque identities and complete provenance in the keyboard scroll region", async () => {
  const instrument = "declared-" + "x".repeat(247);
  const source = "source-" + "s".repeat(249);
  const recordId = "record-" + "r".repeat(249);
  handlers.set(`GET ${path}`, () => reply(evidence([{ ...row, instrument_id: instrument, source_id: source, record_id: recordId }])));
  await mount();
  const scrollOwner = screen.getByRole("region", { name: "Investment views and evidence" });
  expect(scrollOwner).toHaveAttribute("tabindex", "0");
  scrollOwner.focus(); expect(scrollOwner).toHaveFocus();
  expect(await screen.findByText(instrument)).toHaveTextContent(instrument);
  const records = screen.getByRole("list", { name: "Declared portfolio records" });
  for (const exact of [instrument, source, recordId, row.quantity, row.input_sha256, row.origin, row.observed_at, row.retrieved_at]) expect(records.textContent).toContain(exact);
  expect(screen.getByRole("tab", { name: "Dashboard" })).toBeInTheDocument();
  expect(await screen.findByText("Retained investment dashboard")).toBeVisible();
  expect(calls).toEqual([`GET ${path}`]);
});
it("mounts user-declared evidence beside the retained investment views with exact provenance and missing values", async () => {
  await mount();
  expect(await screen.findByRole("heading", { name: "Canonical portfolio evidence" })).toBeVisible();
  expect(await screen.findByText("synthetic-fund")).toBeVisible();
  await waitFor(() => expect(screen.getByText("Retained investment dashboard")).toBeVisible());
  expect(screen.getByText(/not a complete account book/i)).toBeVisible();
  expect(screen.getByText("1.250 units")).toBeVisible();
  expect(screen.getByText(/Cash amount: unavailable/)).toBeVisible();
  expect(screen.getByText(/Published: unavailable/)).toBeVisible();
  expect(screen.getByText(/2026-01-02T10:00:00\+00:00/)).toBeVisible();
  expect(screen.getByText(/user-statement/)).toBeVisible();
  expect(calls).toEqual([`GET ${path}`]);
});

const inputRecord = { record_id: "manual-2", kind: "holding", instrument_id: "synthetic-bond", venue: "declared-register", currency: "INR", quantity_unit: "units", quantity: "1.250", observed_at: "2026-01-02T10:00:00+00:00", cash_amount: null };
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : 1).map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;
  return JSON.stringify(value);
}
const sha = (value: string) => createHash("sha256").update(value).digest("hex");
function imported(origin = "manual", input = canonical([inputRecord])) {
  const input_sha256 = sha(input);
  const batch_id = sha(canonical({ schema_version: 1, scope, source_id: "new-source", origin, input_sha256, records: [inputRecord], verification: "user_declared", complete: false, execution_authority: false }));
  return { receipt: { batch_id, input_sha256, count: 1, verification: "user_declared", complete: false, execution_authority: false }, fact: { ...row, ...inputRecord, source_id: "new-source", origin, input_sha256 } };
}
async function fillManual() {
  await screen.findByText("synthetic-fund");
  fireEvent.change(screen.getByLabelText("Evidence source ID"), { target: { value: "new-source" } });
  for (const [field, value] of Object.entries(inputRecord)) {
    if (field === "kind" || value === null) continue;
    fireEvent.change(screen.getByLabelText(field), { target: { value } });
  }
}
it("submits an explicit manual record without client authority and confirms its exact receipt and readback", async () => {
  const { receipt, fact } = imported();
  let finish!: (response: Response) => void;
  handlers.set(`POST ${path}`, init => {
    expect(JSON.parse(String(init.body))).toEqual({ origin: "manual", source_id: "new-source", records: [inputRecord] });
    handlers.set(`GET ${path}`, () => new Promise(resolve => { finish = resolve; }));
    return reply(receipt, 201);
  });
  await mount(); await fillManual();
  fireEvent.click(screen.getByRole("button", { name: "Submit declared evidence" }));
  await waitFor(() => expect(finish).toBeDefined());
  expect(screen.queryByText(/Receipt and declared-fact readback matched/)).not.toBeInTheDocument();
  await act(async () => { finish(reply(evidence([row, fact]))); });
  expect(await screen.findByText(/Receipt and declared-fact readback matched/)).toBeVisible();
  expect(screen.getByText(new RegExp(receipt.batch_id))).toBeVisible();
  expect(screen.getByText("synthetic-bond")).toBeVisible();
  expect(screen.getByLabelText("instrument_id")).toHaveValue("");
  expect(client.getMutationCache().getAll()).toHaveLength(0);
  expect(JSON.stringify(localStorage)).not.toContain("synthetic-bond");
  expect(JSON.stringify(sessionStorage)).not.toContain("synthetic-bond");
  expect(calls).toEqual([`GET ${path}`, `POST ${path}`, `GET ${path}`]);
});
it("imports an explicitly supplied statement_csv without retaining its raw body in browser caches", async () => {
  const csv = `${Object.keys(inputRecord).join(",")}\n${Object.values(inputRecord).join(",")}\n`;
  const { receipt, fact } = imported("statement_csv", csv);
  handlers.set(`POST ${path}`, init => {
    expect(JSON.parse(String(init.body))).toEqual({ origin: "statement_csv", source_id: "new-source", csv });
    handlers.set(`GET ${path}`, () => reply(evidence([row, fact])));
    return reply(receipt, 201);
  });
  await mount(); await screen.findByText("synthetic-fund");
  fireEvent.click(screen.getByRole("button", { name: "Statement CSV" }));
  fireEvent.change(screen.getByLabelText("Evidence source ID"), { target: { value: "new-source" } });
  fireEvent.change(screen.getByLabelText("Statement CSV content"), { target: { value: csv } });
  fireEvent.click(screen.getByRole("button", { name: "Submit declared evidence" }));
  expect(await screen.findByText(/Receipt and declared-fact readback matched/)).toBeVisible();
  expect(screen.getByLabelText("Statement CSV content")).toHaveValue("");
  expect(JSON.stringify(client.getQueryCache().getAll().map(query => query.state.data))).not.toContain(csv);
  expect(client.getMutationCache().getAll()).toHaveLength(0);
  expect(JSON.stringify(localStorage)).not.toContain(csv);
  expect(JSON.stringify(sessionStorage)).not.toContain(csv);
});

it.each([
  ["malformed row", { ...evidence(), records: [row, { ...row, quantity: 1.25 }] }],
  ["missing metadata", { ...evidence(), records: [{ ...row, retrieved_at: undefined }] }],
  ["complete claim", { ...evidence(), complete: true }],
  ["conflicting rows", evidence([row, { ...row, quantity: "20" }])],
  ["negative holding", evidence([{ ...row, quantity: "-1" }])],
  ["invalid calendar date", evidence([{ ...row, observed_at: "2026-02-30T10:00:00Z" }])],
])("refuses the entire %s read without inventing an empty account", async (_label, data) => {
  handlers.set(`GET ${path}`, () => reply(data)); await mount();
  expect(await screen.findByRole("alert")).toHaveTextContent(/invalid|incomplete/);
  expect(screen.queryByText("synthetic-fund")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Submit declared evidence" })).toBeDisabled();
});
it("labels a genuine empty evidence set unavailable, not an empty account", async () => {
  handlers.set(`GET ${path}`, () => reply(evidence([]))); await mount();
  expect(await screen.findByText(/does not establish an empty or flat account/)).toBeVisible();
});
it.each([[403, "portfolio_evidence_not_authorised"], [409, "portfolio_evidence_conflict"], [422, "invalid_portfolio_evidence"], [503, "portfolio_evidence_store_unavailable"]])("retains explicit HTTP %s refusal without success or automatic retry", async (status, code) => {
  handlers.set(`POST ${path}`, () => new Response(JSON.stringify({ status: "error", code }), { status }));
  await mount(); await fillManual(); fireEvent.click(screen.getByRole("button", { name: "Submit declared evidence" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(code);
  expect(screen.queryByText(/Receipt and declared-fact readback matched/)).not.toBeInTheDocument();
  expect(calls).toEqual([`GET ${path}`, `POST ${path}`]);
});
it.each(["receipt", "readback", "scope"])("refuses a mismatching %s after submission", async defect => {
  const { receipt, fact } = imported();
  handlers.set(`POST ${path}`, () => {
    handlers.set(`GET ${path}`, () => reply(defect === "scope" ? { ...evidence([fact]), scope: { ...scope, generation: 99 } } : evidence(defect === "readback" ? [row] : [fact])));
    return reply(defect === "receipt" ? { ...receipt, batch_id: "b".repeat(64) } : receipt, 201);
  });
  await mount(); await fillManual(); fireEvent.click(screen.getByRole("button", { name: "Submit declared evidence" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/mismatch/);
  expect(screen.queryByText(/Receipt and declared-fact readback matched/)).not.toBeInTheDocument();
});
it.each(["account", "session"])("fences a deferred submission after %s retirement and leaves the new draft alone", async retirement => {
  const { receipt } = imported(); let finish!: (response: Response) => void;
  handlers.set(`POST ${path}`, () => new Promise(resolve => { finish = resolve; }));
  await mount(); await fillManual(); fireEvent.click(screen.getByRole("button", { name: "Submit declared evidence" }));
  await waitFor(() => expect(finish).toBeDefined());
  await act(async () => { if (retirement === "account") useBrokerStore.setState({ activeAccountId: "native:synthetic:B" }); else useAuthStore.setState({ sessionGeneration: 5 }); });
  await screen.findByText("synthetic-fund");
  fireEvent.change(screen.getByLabelText("instrument_id"), { target: { value: "B-draft" } });
  await act(async () => { finish(reply(receipt, 201)); });
  expect(screen.getByLabelText("instrument_id")).toHaveValue("B-draft");
  expect(screen.queryByText(/Receipt and declared-fact readback matched/)).not.toBeInTheDocument();
  expect(screen.queryByText(new RegExp(receipt.batch_id))).not.toBeInTheDocument();
  expect(calls).toEqual([`GET ${path}`, `POST ${path}`, `GET ${path}`]);
});
it("accepts a selected CSV file as an explicit draft without submitting automatically", async () => {
  const csv = `${Object.keys(inputRecord).join(",")}\n${Object.values(inputRecord).join(",")}\n`;
  await mount(); await screen.findByText("synthetic-fund");
  fireEvent.click(screen.getByRole("button", { name: "Statement CSV" }));
  fireEvent.change(screen.getByLabelText("Choose statement CSV"), { target: { files: [new File([csv], "synthetic.csv", { type: "text/csv" })] } });
  await waitFor(() => expect(screen.getByLabelText("Statement CSV content")).toHaveValue(csv));
  expect(calls).toEqual([`GET ${path}`]);
  fireEvent.click(screen.getByRole("button", { name: "Clear input" }));
  expect(screen.getByLabelText("Statement CSV content")).toHaveValue("");
});
it("refuses an invalid UTF-8 statement file instead of silently repairing bytes", async () => {
  await mount(); await screen.findByText("synthetic-fund");
  fireEvent.click(screen.getByRole("button", { name: "Statement CSV" }));
  fireEvent.change(screen.getByLabelText("Choose statement CSV"), { target: { files: [new File([new Uint8Array([0xff, 0xfe, 0x61])], "invalid.csv", { type: "text/csv" })] } });
  expect(await screen.findByRole("alert")).toHaveTextContent(/UTF-8/);
  expect(screen.getByLabelText("Statement CSV content")).toHaveValue("");
  expect(calls).toEqual([`GET ${path}`]);
});
it("refuses a server scope change during evidence refresh until the session view is retired", async () => {
  await mount(); await screen.findByText("synthetic-fund");
  handlers.set(`GET ${path}`, () => reply({ ...evidence(), scope: { ...scope, generation: 9 } }));
  fireEvent.click(screen.getByRole("button", { name: "Read portfolio evidence" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/scope mismatch/i);
  expect(screen.queryByText("synthetic-fund")).not.toBeInTheDocument();
});
it("refuses conflicting CSV rows before any mutation", async () => {
  const csv = `${Object.keys(inputRecord).join(",")}\n${Object.values(inputRecord).join(",")}\n${Object.values({ ...inputRecord, quantity: "2" }).join(",")}\n`;
  await mount(); await screen.findByText("synthetic-fund");
  fireEvent.click(screen.getByRole("button", { name: "Statement CSV" }));
  fireEvent.change(screen.getByLabelText("Evidence source ID"), { target: { value: "new-source" } });
  fireEvent.change(screen.getByLabelText("Statement CSV content"), { target: { value: csv } });
  fireEvent.click(screen.getByRole("button", { name: "Submit declared evidence" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/conflicting/i);
  expect(calls).toEqual([`GET ${path}`]);
});
