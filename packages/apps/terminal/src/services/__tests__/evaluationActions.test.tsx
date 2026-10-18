import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { runBacktest } from "../ftApi";
import TestingEvidencePanel from "@/routes/TestingEvidencePanel";
import { startTraining, adoptArtifact, scoreEvaluation, controlTraining, readEvaluationEvidence } from "../evaluationActions";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { useConnectionStore } from "@/stores/connectionStore";

const experiment = "a".repeat(32);
const trial = "b".repeat(32);
const config = { symbol: "TEST", exchange: "NSE", interval: "1d", start_date: "2025-01-01", end_date: "2025-01-02", strategy: "EMACrossover", initial_capital: 100000, position_size_pct: 10 };
const result = { trades: [], equity_curve: [], final_equity: 100000, total_bars: 2, metrics: { total_return: 0, sharpe_ratio: 0, sortino_ratio: 0, max_drawdown: 0, win_rate: 0, profit_factor: 0, total_trades: 0, expectancy: 0 } };
let unexpected: string[];
beforeEach(() => {
  unexpected = [];
  useAuthStore.setState(s => ({ status: "logged-in", token: "synthetic-r17", username: "synthetic", sessionGeneration: s.sessionGeneration + 1 }));
  useBrokerStore.setState({ activeAccountId: "native:dhan:synthetic-A" });
  useModeStore.setState({ mode: "live" });
  useConnectionStore.setState({ apiKey: "" });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); expect(unexpected).toEqual([]); });

const training = { request_id: "training-one", payload: { model_name: "test-model-v1", training_type: "lora", format_type: "chatml", hf_dataset: "synthetic/remote-dataset" }, lineage: { dataset: "d".repeat(64), run_id: "run-one" } };
const job = { id: training.request_id, request_digest: "e".repeat(64), lineage: training.lineage, state: "accepted", remote_job_id: "remote-one", cancellation: "not-requested", deletion: "not-requested", weight_unlearning: "unavailable", publication: "disabled", events: [] };
function response(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status }); }
const registeredRequests = new Set([
  "POST /ft-api/api/v1/backtest/run", "POST /ft-api/api/v1/backtest/training/jobs",
  "GET /ft-api/api/v1/backtest/training/jobs/training-one", "POST /ft-api/api/v1/backtest/training/jobs/training-one/cancel",
  "POST /ft-api/api/v1/backtest/evaluation/suites/suite-one/score", "POST /ft-api/api/v1/backtest/adoptions", "GET /ft-api/api/v1/backtest/adoptions/adopt-one",
]);
function wire(handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => {
    if (!registeredRequests.has(`${init.method} ${url}`)) { unexpected.push(`${init.method} ${url}`); throw new Error("Unregistered transport"); }
    try { return await handler(url, init); }
    catch (error) { if (error instanceof Error && error.name === "AssertionError") unexpected.push(String(error)); throw error; }
  });
  vi.stubGlobal("fetch", fn); return fn;
}
it("does not resend an uncertain training start and refuses changed payload under the same request identity", async () => {
  const fetch = wire((url, init) => {
    if (url === "/ft-api/api/v1/backtest/training/jobs" && init.method === "POST") return Promise.reject(new Error("synthetic lost reply"));
    if (url === "/ft-api/api/v1/backtest/training/jobs/training-one" && init.method === "GET") return response({ status: "success", data: { ...job, state: "unknown" } });
    unexpected.push(`${init.method} ${url}`); throw new Error("Unregistered transport");
  });
  await expect(startTraining(training)).rejects.toThrow("Unknown remote outcome");
  expect(fetch).toHaveBeenCalledTimes(2);
  await expect(startTraining(training)).rejects.toThrow(/already sent/);
  await expect(startTraining({ ...training, payload: { ...training.payload, model_name: "other" } })).rejects.toThrow(/identity conflict/);
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("allows an explicit confirmed attempt after core reported pre-dispatch authority unavailable", async () => {
  let available = false;
  const fetch = wire((url, init) => {
    if (url === "/ft-api/api/v1/backtest/training/jobs" && init.method === "POST") {
      return available ? response({ status: "success", data: job }, 202) : response({ status: "unavailable", message: "Core authority/qualified adapter not configured" }, 503);
    }
    if (url === "/ft-api/api/v1/backtest/training/jobs/training-one" && init.method === "GET") return response({ status: "success", data: job });
    unexpected.push(`${init.method} ${url}`); throw new Error("Unregistered transport");
  });
  await expect(startTraining(training)).rejects.toThrow("unavailable: Core authority/qualified adapter not configured");
  expect(fetch).toHaveBeenCalledTimes(1);
  available = true;
  expect(await startTraining(training)).toMatchObject({ id: "training-one", state: "accepted" });
  expect(fetch).toHaveBeenCalledTimes(3);
});

it.each([null, [], { id: "foreign" }, { ...job, state: "invented" }])("retains unknown mutation outcome for malformed or mismatched ACK %#", async acknowledgement => {
  const fetch = wire((url, init) => {
    if (init.method === "POST" && url === "/ft-api/api/v1/backtest/training/jobs") return response({ status: "success", data: acknowledgement }, 202);
    if (init.method === "GET" && url === "/ft-api/api/v1/backtest/training/jobs/training-one") return response({ status: "success", data: job });
    unexpected.push(`${init.method} ${url}`); throw new Error("Unregistered transport");
  });
  await expect(startTraining(training)).rejects.toThrow("Unknown remote outcome");
  expect(fetch).toHaveBeenCalledTimes(2);
});

it.each([
  [503, { status: "unavailable", message: "Independent prospective evidence resolver required" }, "unavailable"],
  [403, { status: "error", code: "sealed_access_not_authorised" }, "refused"],
  [409, { status: "error", message: "Immutable request identity conflict" }, "refused"],
  [422, { status: "refused", message: "Frozen qualification prerequisites not satisfied" }, "refused"],
] as const)("preserves exact core refusal without follow-on mutation (%i)", async (status, body, outcome) => {
  const fetch = wire((url, init) => {
    if (url !== "/ft-api/api/v1/backtest/evaluation/suites/suite-one/score" || init.method !== "POST") unexpected.push(`${init.method} ${url}`);
    return response(body, status);
  });
  await expect(scoreEvaluation("suite-one", trial)).rejects.toThrow(outcome);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it.each(["id", "request_digest", "lineage", "remote_job_id"])("rejects mismatched training readback %s", async field => {
  const changed = { ...job, [field]: field === "lineage" ? { ...job.lineage, run_id: "foreign-run" } : field === "request_digest" ? "f".repeat(64) : "foreign" };
  wire((url, init) => {
    if (init.method === "POST" && url === "/ft-api/api/v1/backtest/training/jobs") return response({ status: "success", data: job }, 202);
    if (init.method === "GET" && url === "/ft-api/api/v1/backtest/training/jobs/training-one") return response({ status: "success", data: changed });
    unexpected.push(`${init.method} ${url}`); throw new Error("Unregistered transport");
  });
  await expect(startTraining(training)).rejects.toThrow("Unknown remote outcome");
});

it.each([null, [], {}, { ...training, grant: "not-authority" }, { ...training, payload: { ...training.payload, local_datasets: ["/private/data"] } }])("refuses invalid training DTO before any transport %#", async input => {
  const fetch = wire(() => { unexpected.push("invalid DTO sent"); throw new Error("No request allowed"); });
  await expect(async () => startTraining(input)).rejects.toThrow(); expect(fetch).not.toHaveBeenCalled();
});

it("refuses invalid adoption generation and client qualification without transport", async () => {
  const fetch = wire(() => { unexpected.push("invalid DTO sent"); throw new Error("No request allowed"); });
  for (const expected_generation of [1.5, -1, true, "4"]) {
    await expect(async () => adoptArtifact({ request_id: "adopt-one", run_id: "run-one", role: "reasoning", candidate: "candidate", expected_generation, kind: "adopt" })).rejects.toThrow();
  }
  expect(fetch).not.toHaveBeenCalled();
});

it.each(["run_id", "candidate", "expected_generation", "kind"])("refuses adoption completion when exact request readback changes %s", async field => {
  const body = { request_id: "adopt-one", run_id: "run-one", role: "reasoning", candidate: "candidate-one", expected_generation: 2, kind: "adopt" };
  const request = { run_id: body.run_id, role: body.role, candidate: body.candidate, expected_generation: body.expected_generation, kind: body.kind };
  const bound = { run_id: body.run_id, role: body.role, account: "paper:sandbox", environment: "paper", generation: 3, config_generation: 1, risk_fingerprint: "risk", frontier: "frontier", protection_id: "protector", protection_verified: true, binding: body.candidate, entries_armed: false };
  const good = { id: body.request_id, request, status: "completed", phase: "verified", bound, events: [] };
  const bad = { ...good, request: { ...request, [field]: field === "expected_generation" ? 3 : field === "kind" ? "rollback" : "foreign" } };
  const fetch = wire((url, init) => {
    if (url === "/ft-api/api/v1/backtest/adoptions" && init.method === "POST") return response({ status: "success", data: good }, 202);
    if (url === "/ft-api/api/v1/backtest/adoptions/adopt-one" && init.method === "GET") return response({ status: "success", data: bad });
    unexpected.push(`${init.method} ${url}`); throw new Error("Unregistered transport");
  });
  await expect(adoptArtifact(body)).rejects.toThrow("Unknown remote outcome");
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("reads cancellation acknowledgment without claiming stopped and preserves unsupported deletion", async () => {
  const acknowledged = { ...job, cancellation: "requested" };
  const fetch = wire((url, init) => {
    if (init.method === "POST" && url === "/ft-api/api/v1/backtest/training/jobs/training-one/cancel") return response({ status: "success", data: acknowledged }, 202);
    if (init.method === "GET" && url === "/ft-api/api/v1/backtest/training/jobs/training-one") return response({ status: "success", data: acknowledged });
    unexpected.push(`${init.method} ${url}`); throw new Error("Unregistered transport");
  });
  expect(await controlTraining("training-one", "cancel")).toMatchObject({ state: "accepted", cancellation: "requested", deletion: "not-requested", weight_unlearning: "unavailable" });
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("rejects unknown read statuses instead of trusting a loose success object", async () => {
  wire((url, init) => {
    if (url !== "/ft-api/api/v1/backtest/training/jobs/training-one" || init.method !== "GET") unexpected.push(`${init.method} ${url}`);
    return response({ status: "success", data: { ...job, state: "invented" } });
  });
  await expect(readEvaluationEvidence("training/jobs", "training-one")).rejects.toThrow("Malformed evidence");
});

it.each(["F".repeat(64), ` ${"f".repeat(64)}`, "", "not-a-manifest"])("does not repair or dispatch a malformed explicit snapshot %#", async data_manifest_id => {
  const fetch = wire(() => { unexpected.push("Malformed manifest dispatched"); return response({ status: "success", data: result }); });
  await expect(runBacktest({ ...config, data_manifest_id })).rejects.toThrow();
  expect(fetch).not.toHaveBeenCalled();
});
it("never substitutes preview data for an explicitly selected immutable snapshot", async () => {
  useAuthStore.setState({ token: "demo-user" });
  const fetch = wire(() => { unexpected.push("Preview transport"); return response({}); });
  await expect(runBacktest({ ...config, data_manifest_id: "f".repeat(64) })).rejects.toThrow(/preview/i);
  expect(fetch).not.toHaveBeenCalled();
});
it.each([null, [], { final_equity: 0 }, { ...result, metrics: { ...result.metrics, total_trades: "zero" } }])("refuses malformed backtest result while retaining real returned references %#", async data => {
  wire(() => new Response(JSON.stringify({ status: "success", data }), { headers: { "X-Experiment-Id": experiment, "X-Trial-Id": trial } }));
  render(<TestingEvidencePanel />);
  await act(async () => { await expect(runBacktest(config)).rejects.toThrow(/Malformed backtest result/); });
  expect(screen.getByLabelText("Captured backtest receipts")).toHaveTextContent(trial);
});
it.each([new Headers(), new Headers({ "X-Trial-Id": trial }), new Headers({ "X-Trial-Id": "bad-id", "X-Experiment-Id": experiment })])("does not invent absent or invalid immutable response references %#", async headers => {
  wire(() => new Response(JSON.stringify({ status: "success", data: result }), { headers }));
  render(<TestingEvidencePanel />);
  await act(async () => expect(await runBacktest(config)).toEqual(result));
  expect(screen.getByLabelText("Captured backtest receipts")).toHaveTextContent("missing or malformed response headers");
  expect(screen.queryByRole("button", { name: `Read trial ${trial}` })).not.toBeInTheDocument();
});
it.each(["network", "malformed_json"])("keeps an uncertain backtest outcome explicit without retry for %s", async failure => {
  const fetch = wire((url, init) => {
    if (url !== "/ft-api/api/v1/backtest/run" || init.method !== "POST") unexpected.push(`${init.method} ${url}`);
    return failure === "network" ? Promise.reject(new Error("synthetic lost reply")) : Promise.resolve(new Response("{bad"));
  });
  await expect(runBacktest(config)).rejects.toThrow("Unknown remote outcome");
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("preserves scoped HTTP failure diagnostics at the real backtest caller", async () => {
  useOperatorSignalStore.setState({ observedBackendUnreachable: false });
  wire((url, init) => {
    if (url !== "/ft-api/api/v1/backtest/run" || init.method !== "POST") unexpected.push(`${init.method} ${url}`);
    return response({ status: "unavailable", message: "Backend unreachable", data: { reason: "synthetic" } }, 503);
  });
  await expect(runBacktest(config)).rejects.toMatchObject({ message: "Backend unreachable", status: 503, data: { reason: "synthetic" } });
  expect(useOperatorSignalStore.getState().observedBackendUnreachable).toBe(true);
});
it("retains returned immutable failure references and preserves the original core error", async () => {
  wire(() => new Response(JSON.stringify({ status: "error", message: "Backtest did not complete" }), { status: 500, headers: { "X-Experiment-Id": experiment, "X-Trial-Id": trial } }));
  render(<TestingEvidencePanel />);
  await act(async () => { await expect(runBacktest(config)).rejects.toThrow("Backtest did not complete"); });
  expect(screen.getByLabelText("Captured backtest receipts")).toHaveTextContent(`HTTP 500`);
  expect(screen.getByLabelText("Captured backtest receipts")).toHaveTextContent(trial);
});
it.each(["account", "logout"])("retires late backtest results and receipts after %s", async change => {
  let finish: (value: Response) => void = () => { throw new Error("Not entered"); };
  wire((url, init) => {
    if (url !== "/ft-api/api/v1/backtest/run" || init.method !== "POST") unexpected.push(`${init.method} ${url}`);
    return new Promise(resolve => { finish = resolve; });
  });
  render(<TestingEvidencePanel />);
  const pending = runBacktest(config); const rejection = expect(pending).rejects.toThrow("scope retired");
  await act(async () => {
    if (change === "account") useBrokerStore.setState({ activeAccountId: "native:dhan:synthetic-B" });
    else useAuthStore.getState().setLoggedOut();
    finish(new Response(JSON.stringify({ status: "success", data: result }), { headers: { "X-Experiment-Id": experiment, "X-Trial-Id": trial } }));
    await rejection;
  });
  expect(screen.getByLabelText("Captured backtest receipts")).not.toHaveTextContent(trial);
});

it("captures the real backtest response headers automatically without replacing its result", async () => {
  const transport = vi.fn(async (url: string, init?: RequestInit) => {
    try {
      expect(url).toBe("/ft-api/api/v1/backtest/run");
      expect(init?.method).toBe("POST");
      expect(JSON.parse(String(init?.body))).toEqual(config);
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer synthetic-r17");
    } catch (error) { unexpected.push(String(error)); throw error; }
    return new Response(JSON.stringify({ status: "success", data: result }), { headers: { "X-Experiment-Id": experiment, "X-Trial-Id": trial } });
  });
  vi.stubGlobal("fetch", transport);
  render(<TestingEvidencePanel />);
  await act(async () => { expect(await runBacktest(config)).toEqual(result); });
  expect(screen.getByLabelText("Captured backtest receipts")).toHaveTextContent(experiment);
  expect(screen.getByLabelText("Captured backtest receipts")).toHaveTextContent(trial);
  expect(transport).toHaveBeenCalledTimes(1);
});
