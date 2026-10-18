import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import TestingEvidencePanel from "../TestingEvidencePanel";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";

const trial = "b".repeat(32);
const experiment = "a".repeat(32);
const record = { id: trial, experiment_id: experiment, status: "completed", evidence: { qualified: false, metric: null } };
let unexpected: string[];
beforeEach(() => {
  unexpected = [];
  useAuthStore.setState(s => ({ status: "logged-in", token: "synthetic-evidence", username: "synthetic", sessionGeneration: s.sessionGeneration + 1 }));
  useBrokerStore.setState({ activeAccountId: "native:dhan:synthetic-A" });
  useConnectionStore.setState({ apiKey: "synthetic-key-not-operator-authority" });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); expect(unexpected).toEqual([]); });
function respond(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status }); }
function transport(handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => {
    try { return await handler(url, init); } catch (error) { unexpected.push(String(error)); throw error; }
  });
  vi.stubGlobal("fetch", fn); return fn;
}

it("keeps the exact immutable ID bound while its read is pending and preserves null evidence", async () => {
  let finish: (response: Response) => void = () => { throw new Error("read not started"); };
  const fetch = transport((url) => {
    expect(url).toBe(`/ft-api/api/v1/backtest/trials/${trial}`);
    return new Promise<Response>(resolve => { finish = resolve; });
  });
  render(<TestingEvidencePanel />); const user = userEvent.setup();
  await user.type(screen.getByLabelText("Immutable evidence ID"), trial);
  await user.click(screen.getByRole("button", { name: "Read evidence" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  expect(screen.getByLabelText("Immutable evidence ID")).toBeDisabled();
  expect(screen.getByLabelText("Evidence kind")).toBeDisabled();
  await act(async () => finish(respond({ status: "success", data: record })));
  expect(await screen.findByLabelText("Exact core evidence")).toHaveTextContent('"metric": null');
  expect(fetch).toHaveBeenCalledWith(`/ft-api/api/v1/backtest/trials/${trial}`, expect.objectContaining({ cache: "no-store" }));
  await user.clear(screen.getByLabelText("Immutable evidence ID"));
  expect(screen.queryByLabelText("Exact core evidence")).not.toBeInTheDocument();
});

it("launches a sealed evaluation only on confirmation and reads the exact trial without client qualification", async () => {
  const scored = { ...record, evidence: { qualified: true, suite: "suite-1", metrics: { correct: 1 } } };
  const fetch = transport((url, init) => {
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer synthetic-evidence");
    expect(headers.has("X-API-Key")).toBe(false);
    if (init.method === "POST" && url === "/ft-api/api/v1/backtest/evaluation/suites/suite-1/score") {
      expect(JSON.parse(String(init.body))).toEqual({ trial_id: trial });
      return respond({ status: "completed", data: scored });
    }
    expect(init.method).toBe("GET");
    expect(url).toBe(`/ft-api/api/v1/backtest/trials/${trial}`);
    return respond({ status: "success", data: scored });
  });
  render(<TestingEvidencePanel />); const user = userEvent.setup();
  await user.type(screen.getByLabelText("Frozen suite ID"), "suite-1");
  await user.type(screen.getByLabelText("Evaluation trial ID"), trial);
  await user.click(screen.getByRole("button", { name: "Launch evaluation" }));
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.getByRole("alertdialog")).toHaveTextContent(trial);
  await user.click(screen.getByRole("button", { name: "Confirm action" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Evaluation completed");
  expect(screen.getByLabelText("Exact core evidence")).toHaveTextContent('"qualified": true');
  expect(fetch).toHaveBeenCalledTimes(2);
});

const trainingBody = { request_id: "training-one", payload: { model_name: "test-model-v1", training_type: "lora", format_type: "chatml", hf_dataset: "synthetic/remote-dataset" }, lineage: { dataset: "d".repeat(64), run_id: "run-one" } };
const job = { id: "training-one", request_digest: "e".repeat(64), lineage: trainingBody.lineage, state: "accepted", remote_job_id: "remote-one", cancellation: "not-requested", deletion: "not-requested", weight_unlearning: "unavailable", publication: "disabled", events: [] };
async function fillFields(user: ReturnType<typeof userEvent.setup>, fields: Record<string, string>) {
  for (const [label, value] of Object.entries(fields)) await user.type(screen.getByLabelText(label), value);
}
it("submits an exact core-prepared optional training request and confirms acknowledged cancellation only", async () => {
  let current = job;
  const fetch = transport((url, init) => {
    if (url === "/ft-api/api/v1/backtest/training/jobs" && init.method === "POST") {
      expect(JSON.parse(String(init.body))).toEqual(trainingBody);
      return respond({ status: "success", data: current }, 202);
    }
    if (url === "/ft-api/api/v1/backtest/training/jobs/training-one/cancel" && init.method === "POST") {
      expect(JSON.parse(String(init.body))).toEqual({});
      current = { ...job, cancellation: "requested" };
      return respond({ status: "success", data: current }, 202);
    }
    if (url === "/ft-api/api/v1/backtest/training/jobs/training-one/reconcile" && init.method === "POST") {
      expect(JSON.parse(String(init.body))).toEqual({});
      current = { ...job, state: "cancelled", cancellation: "confirmed" };
      return respond({ status: "success", data: current }, 202);
    }
    expect(url).toBe("/ft-api/api/v1/backtest/training/jobs/training-one"); expect(init.method).toBe("GET");
    return respond({ status: "success", data: current });
  });
  render(<TestingEvidencePanel />); const user = userEvent.setup();
  await fillFields(user, { "Training request ID": "training-one", "Training model": "test-model-v1", "Training method": "lora", "Training format": "chatml", "Registered remote dataset": "synthetic/remote-dataset", "Immutable batch ID": trainingBody.lineage.dataset, "Training run ID": "run-one" });
  await user.click(screen.getByRole("button", { name: "Submit prepared training" }));
  expect(fetch).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Confirm action" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Training accepted; not completed");
  expect(fetch).toHaveBeenCalledTimes(2);
  await user.selectOptions(screen.getByLabelText("Evidence kind"), "training/jobs");
  await user.clear(screen.getByLabelText("Immutable evidence ID"));
  await user.type(screen.getByLabelText("Immutable evidence ID"), "training-one");
  await user.click(screen.getByRole("button", { name: "Request training cancellation" }));
  expect(fetch).toHaveBeenCalledTimes(2);
  await user.click(screen.getByRole("button", { name: "Confirm action" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Cancellation requested; remote stop is not confirmed"));
  expect(fetch).toHaveBeenCalledTimes(4);
  await user.click(screen.getByRole("button", { name: "Reconcile exact target" }));
  await user.click(screen.getByRole("button", { name: "Confirm action" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Remote stop confirmed"));
  expect(fetch).toHaveBeenCalledTimes(6);
  expect(screen.getByRole("button", { name: "Delete training data" })).toBeDisabled();
  expect(screen.getByText(/No core deletion route/)).toBeInTheDocument();
});

const adoptionRequest = { request_id: "adopt-one", run_id: "run-one", role: "reasoning", candidate: "candidate-v2", expected_generation: 4, kind: "adopt" };
const bound = { run_id: "run-one", role: "reasoning", account: "paper:sandbox", environment: "paper", generation: 5, config_generation: 2, risk_fingerprint: "risk-one", frontier: "frontier-one", protection_id: "protector-one", protection_verified: true, binding: "candidate-v2", entries_armed: false };
function adoptionRecord(request = adoptionRequest) {
  const { request_id, ...body } = request;
  return { id: request_id, request: body, status: "completed", phase: "verified", bound: { ...bound, binding: request.candidate, generation: request.expected_generation + 1 }, events: [] };
}
it("adopts and rolls back only the explicit version/generation after confirmation and exact readback", async () => {
  let expected = adoptionRequest;
  const fetch = transport((url, init) => {
    if (init.method === "POST") {
      expect(url).toBe("/ft-api/api/v1/backtest/adoptions");
      expect(JSON.parse(String(init.body))).toEqual(expected);
      return respond({ status: "success", data: adoptionRecord(expected) }, 202);
    }
    expect(init.method).toBe("GET"); expect(url).toBe(`/ft-api/api/v1/backtest/adoptions/${expected.request_id}`);
    return respond({ status: "success", data: adoptionRecord(expected) });
  });
  render(<TestingEvidencePanel />); const user = userEvent.setup();
  await fillFields(user, { "Adoption request ID": "adopt-one", "Target run ID": "run-one", "Target role": "reasoning", "Candidate version ID": "candidate-v2", "Expected run generation": "4" });
  await user.click(screen.getByRole("button", { name: "Request adoption or rollback" }));
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.getByRole("alertdialog")).toHaveTextContent("candidate-v2");
  await user.click(screen.getByRole("button", { name: "Confirm action" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Adoption completed; exact core binding read back");
  expected = { ...adoptionRequest, request_id: "rollback-one", candidate: "candidate-v1", expected_generation: 5, kind: "rollback" };
  for (const [label, value] of Object.entries({ "Adoption request ID": "rollback-one", "Candidate version ID": "candidate-v1", "Expected run generation": "5" })) {
    await user.clear(screen.getByLabelText(label)); await user.type(screen.getByLabelText(label), value);
  }
  await user.selectOptions(screen.getByLabelText("Adoption operation"), "rollback");
  await user.click(screen.getByRole("button", { name: "Request adoption or rollback" }));
  expect(fetch).toHaveBeenCalledTimes(2);
  await user.click(screen.getByRole("button", { name: "Confirm action" }));
  await waitFor(() => expect(screen.getByLabelText("Exact core evidence")).toHaveTextContent('"id": "rollback-one"'));
  expect(screen.getByRole("status")).toHaveTextContent("Rollback completed; exact core binding read back");
  expect(fetch).toHaveBeenCalledTimes(4);
});

it("launches an explicit immutable history snapshot and retains the result beside exact readback", async () => {
  const manifest = "f".repeat(64);
  const result = { trades: [], equity_curve: [], metrics: { total_return: 0, sharpe_ratio: 0, sortino_ratio: 0, max_drawdown: 0, win_rate: 0, profit_factor: 0, total_trades: 0, expectancy: 0 }, final_equity: 100000, total_bars: 2 };
  const fetch = transport((url, init) => {
    if (init.method === "POST") {
      expect(url).toBe("/ft-api/api/v1/backtest/run");
      expect(JSON.parse(String(init.body))).toEqual({ data_manifest_id: manifest, symbol: "TEST", exchange: "NSE", interval: "1d", strategy: "EMACrossover", initial_capital: 100000, position_size_pct: 10, start_date: "", end_date: "" });
      return new Response(JSON.stringify({ status: "success", data: result }), { headers: { "X-Trial-Id": trial, "X-Experiment-Id": experiment } });
    }
    expect(init.method).toBe("GET"); expect(url).toBe(`/ft-api/api/v1/backtest/trials/${trial}`);
    return respond({ status: "success", data: record });
  });
  render(<TestingEvidencePanel />); const user = userEvent.setup();
  await fillFields(user, { "History manifest ID": manifest, "History instrument": "TEST", "History venue": "NSE", "History interval": "1d", "Backtest strategy": "EMACrossover" });
  await user.click(screen.getByRole("button", { name: "Run immutable backtest" }));
  expect(await screen.findByLabelText("Backtest result (not qualification)")).toHaveTextContent('"total_bars": 2');
  expect(await screen.findByLabelText("Exact core evidence")).toHaveTextContent(trial);
  expect(screen.getByLabelText("Captured backtest receipts")).toHaveTextContent(experiment);
  expect(fetch).toHaveBeenCalledTimes(2);
});

it.each(["account", "logout"])("freezes evaluation identity then retires the pending result on %s without hidden read or resend", async change => {
  let finish: (value: Response) => void = () => { throw new Error("Not entered"); };
  let entered = false;
  const fetch = transport((url, init) => {
    expect(url).toBe("/ft-api/api/v1/backtest/evaluation/suites/suite-one/score"); expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ trial_id: trial });
    entered = true; return new Promise(resolve => { finish = resolve; });
  });
  render(<TestingEvidencePanel />); const user = userEvent.setup();
  await fillFields(user, { "Frozen suite ID": "suite-one", "Evaluation trial ID": trial });
  await user.click(screen.getByRole("button", { name: "Launch evaluation" }));
  await user.click(screen.getByRole("button", { name: "Confirm action" }));
  await waitFor(() => expect(entered).toBe(true));
  expect(screen.getByLabelText("Evaluation trial ID")).toBeDisabled();
  expect(screen.getByLabelText("Training request ID")).toBeDisabled();
  expect(screen.getByLabelText("Candidate version ID")).toBeDisabled();
  expect(screen.getByLabelText("Immutable evidence ID")).toBeDisabled();
  await act(async () => {
    if (change === "account") useBrokerStore.setState({ activeAccountId: "native:dhan:synthetic-B" });
    else useAuthStore.getState().setLoggedOut();
    finish(respond({ status: "completed", data: { ...record, evidence: { suite: "suite-one", qualified: true } } }));
  });
  expect(screen.getByLabelText("Evaluation trial ID")).toHaveValue("");
  expect(screen.queryByLabelText("Exact core evidence")).not.toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(1);
});
it.each(["Current grant and independent qualification required", "Exact independent, prospective and role-specific qualification required", "Rollback target not retained", "Stale run generation"])("shows the actual adoption refusal without local promotion: %s", async reason => {
  const refused = { id: adoptionRequest.request_id, request: adoptionRecord().request, status: "refused", reason, protection_verified: true, unresolved_exposure: false, events: [] };
  const fetch = transport((url, init) => {
    if (init.method === "POST") {
      expect(url).toBe("/ft-api/api/v1/backtest/adoptions"); expect(JSON.parse(String(init.body))).toEqual(adoptionRequest);
      return respond({ status: "success", data: refused }, 202);
    }
    expect(url).toBe("/ft-api/api/v1/backtest/adoptions/adopt-one"); expect(init.method).toBe("GET");
    return respond({ status: "success", data: refused });
  });
  render(<TestingEvidencePanel />); const user = userEvent.setup();
  await fillFields(user, { "Adoption request ID": "adopt-one", "Target run ID": "run-one", "Target role": "reasoning", "Candidate version ID": "candidate-v2", "Expected run generation": "4" });
  await user.click(screen.getByRole("button", { name: "Request adoption or rollback" }));
  await user.click(screen.getByRole("button", { name: "Confirm action" }));
  expect(await screen.findByRole("status")).toHaveTextContent(`Adoption refused: ${reason}`);
  expect(fetch).toHaveBeenCalledTimes(2);
});
it("shows unavailable configured authority exactly and does not retry on remount", async () => {
  const fetch = transport((url, init) => {
    expect(url).toBe("/ft-api/api/v1/backtest/evaluation/suites/suite-one/score"); expect(init.method).toBe("POST");
    return respond({ status: "unavailable", message: "Independent prospective evidence resolver required" }, 503);
  });
  const view = render(<TestingEvidencePanel />); const user = userEvent.setup();
  await fillFields(user, { "Frozen suite ID": "suite-one", "Evaluation trial ID": trial });
  await user.click(screen.getByRole("button", { name: "Launch evaluation" }));
  await user.click(screen.getByRole("button", { name: "Confirm action" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("unavailable: Independent prospective evidence resolver required");
  view.unmount(); render(<TestingEvidencePanel />);
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("clears the old completion label when selecting a different immutable identity", async () => {
  transport((url, init) => { expect(url).toBe(`/ft-api/api/v1/backtest/trials/${trial}`); expect(init.method).toBe("GET"); return respond({ status: "success", data: record }); });
  render(<TestingEvidencePanel />); const user = userEvent.setup();
  await user.type(screen.getByLabelText("Immutable evidence ID"), trial);
  await user.click(screen.getByRole("button", { name: "Read evidence" }));
  expect(await screen.findByRole("status")).toHaveTextContent("completed");
  await user.clear(screen.getByLabelText("Immutable evidence ID"));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("rejects a mismatched immutable read rather than displaying another trial", async () => {
  transport(() => respond({ status: "success", data: { ...record, id: "c".repeat(32) } }));
  render(<TestingEvidencePanel />); const user = userEvent.setup();
  await user.type(screen.getByLabelText("Immutable evidence ID"), trial);
  await user.click(screen.getByRole("button", { name: "Read evidence" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("identity mismatch");
  expect(screen.queryByLabelText("Exact core evidence")).not.toBeInTheDocument();
});
