import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { evaluationScopeKey, useEvaluationScope, useBacktestReceipts, backtestReceiptFor } from "@/services/backtestReceipt";
import { EVIDENCE_KINDS, HistoryBacktestRequest, readEvaluationEvidence, scoreEvaluation, startTraining, controlTraining, evidenceNotice, adoptArtifact, reconcileAdoption, type EvidenceKind, type CoreEvidence } from "@/services/evaluationActions";

import { runBacktest, type BacktestResult } from "@/services/ftApi";

export default function TestingEvidencePanel() {
  const scope = useEvaluationScope();
  return <TestingActions key={scope} scope={scope} />;
}
function TestingActions({ scope }: { scope: string }) {
  const receipts = useBacktestReceipts(scope);
  const [history, setHistory] = useState({ data_manifest_id: "", symbol: "", exchange: "", interval: "", strategy: "", initial_capital: "100000", position_size_pct: "10" });
  const [historyRunId, setHistoryRunId] = useState("");
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null);
  const [kind, setKind] = useState<EvidenceKind>("trials");
  const [id, setId] = useState("");
  const [training, setTraining] = useState({ request_id: "", model_name: "", training_type: "", format_type: "", hf_dataset: "", dataset: "", run_id: "" });
  const [adoption, setAdoption] = useState({ request_id: "", run_id: "", role: "", candidate: "", expected_generation: "" });
  const [adoptionKind, setAdoptionKind] = useState("adopt");
  const [decision, setDecision] = useState("");
  const [suite, setSuite] = useState("");
  const [trial, setTrial] = useState("");
  const [evidence, setEvidence] = useState<CoreEvidence | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [confirmation, setConfirmation] = useState<{ label: string; body: unknown; run: () => Promise<CoreEvidence> } | null>(null);
  const frozen = busy || confirmation !== null;
  async function perform(run: () => Promise<CoreEvidence>) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(""); setNotice(""); setEvidence(null);
    try {
      const result = await run();
      if (scope !== evaluationScopeKey()) return;
      setEvidence(result);
      setNotice(evidenceNotice(result));
    } catch (e) { if (scope === evaluationScopeKey()) setError(String(e)); }
    finally { pending.current = false; if (scope === evaluationScopeKey()) setBusy(false); }
  }
  function selectEvidence(nextKind: EvidenceKind, nextId: string) {
    setKind(nextKind); setId(nextId);
    void perform(() => readEvaluationEvidence(nextKind, nextId, scope));
  }
  return <section className="h-full min-h-0 space-y-4 overflow-auto p-4">
    <h2 className="text-lg font-semibold">Immutable experiment evidence</h2>
    <p className="text-sm text-text-secondary">Core owns authority, independent evaluation, prospective checks, grants, verified handover and rollback. Missing policy remains unavailable. Normal backtests are not qualification; no latest-by-strategy promotion.</p>
    <fieldset disabled={frozen} className="space-y-3">
      <legend className="font-semibold">Captured backtest receipts</legend>
      <ul aria-label="Captured backtest receipts" className="space-y-2 break-all text-sm">{receipts.map((receipt, index) => <li key={index}>
        {receipt.strategy}: {receipt.experimentId} / {receipt.trialId} — HTTP {receipt.httpStatus}. {receipt.reason}
        {receipt.submittedRunId ? <p>Submitted run selector: {receipt.submittedRunId} (not verified control scope). Read the immutable experiment to inspect the core-derived scope.</p> : null}
        {receipt.trialId && <Button variant="outline" onClick={() => selectEvidence("trials", receipt.trialId!)}>Read trial {receipt.trialId}</Button>}
        {receipt.experimentId && <Button variant="outline" onClick={() => selectEvidence("experiments", receipt.experimentId!)}>Read experiment {receipt.experimentId}</Button>}
      </li>)}</ul>
      <p className="text-xs text-text-muted">References are captured automatically from X-Experiment-Id / X-Trial-Id for this session and execution scope, including failed runs. Core remains the durable evidence owner.</p>
      <label className="block text-sm">Evidence kind<select aria-label="Evidence kind" className="ml-2 rounded bg-surface-card p-2" value={kind} onChange={e => { setKind(e.target.value as EvidenceKind); setEvidence(null); setNotice(""); setError(""); }}>{Object.entries(EVIDENCE_KINDS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <Input aria-label="Immutable evidence ID" value={id} onChange={e => { setId(e.target.value); setEvidence(null); setNotice(""); setError(""); }} />
      <Button disabled={!id} onClick={() => void perform(() => readEvaluationEvidence(kind, id, scope))}>Read evidence</Button>
    </fieldset>
    <fieldset disabled={frozen} className="space-y-3 rounded border border-border-default p-3">
      <legend className="font-semibold">Immutable history backtest</legend>
      <p className="text-sm">Explicit selection uses the whole canonical snapshot. Instrument, venue and interval must match. No remote or legacy fallback, no changed date range. Core resolves data scope; these selectors do not grant access.</p>
      <label className="block text-sm">Optional backtest run ID<Input aria-label="Optional backtest run ID" autoComplete="off" value={historyRunId} onChange={event => setHistoryRunId(event.target.value)} placeholder="Exact existing run; blank leaves this backtest unscoped" /></label>
      <p className="text-xs text-text-muted">Selecting a run requires current full operator access and that run’s evaluation.read policy. Core alone stamps immutable control scope; data scope remains separate. No scoring, adoption or trading permission is granted. Whitespace is not repaired; Terminal selection stays unchanged.</p>
      {([["data_manifest_id", "History manifest ID"], ["symbol", "History instrument"], ["exchange", "History venue"], ["interval", "History interval"], ["strategy", "Backtest strategy"], ["initial_capital", "Simulation capital"], ["position_size_pct", "Simulation position size percent"]] as const).map(([key, label]) => <label key={key} className="block text-sm">{label}<Input aria-label={label} value={history[key]} onChange={e => setHistory(previous => ({ ...previous, [key]: e.target.value }))} /></label>)}
      <Button disabled={Object.values(history).some(value => !value)} onClick={() => void perform(async () => {
        const body = HistoryBacktestRequest.parse({ ...history, ...(historyRunId === "" ? {} : { run_id: historyRunId }), initial_capital: Number(history.initial_capital), position_size_pct: Number(history.position_size_pct), start_date: "", end_date: "" });
        setBacktestResult(null);
        const result = await runBacktest(body);
        if (scope !== evaluationScopeKey()) throw new Error("Execution scope retired.");
        setBacktestResult(result);
        const receipt = backtestReceiptFor(result);
        if (!receipt?.trialId) throw new Error("Backtest returned; immutable evidence unavailable. Do not infer qualification.");
        const exact = await readEvaluationEvidence("trials", receipt.trialId, scope);
        if (exact.experiment_id !== receipt.experimentId) throw new Error("Backtest experiment identity mismatch.");
        return exact;
      })}>Run immutable backtest</Button>
    </fieldset>
    <fieldset disabled={frozen} className="space-y-3 rounded border border-border-default p-3">
      <legend className="font-semibold">Independent evaluation</legend>
      <p className="text-sm">Use a core-prepared, non-terminal trial and a frozen suite. A completed ordinary backtest cannot be rescored as a sealed qualification trial. The independent grader and prospective evidence must already be configured in core.</p>
      <label className="block text-sm">Frozen suite ID<Input aria-label="Frozen suite ID" value={suite} onChange={e => setSuite(e.target.value)} /></label>
      <label className="block text-sm">Evaluation trial ID<Input aria-label="Evaluation trial ID" value={trial} onChange={e => setTrial(e.target.value)} /></label>
      <Button disabled={!suite || !trial} onClick={() => setConfirmation({ label: "Consume the sealed evaluation access once", body: { suite, trial_id: trial }, run: () => scoreEvaluation(suite, trial, scope) })}>Launch evaluation</Button>
    </fieldset>
    <fieldset disabled={frozen} className="space-y-3 rounded border border-border-default p-3">
      <legend className="font-semibold">Optional training</legend>
      <p className="text-sm">Submit only an exact request already prepared by core, with its immutable batch and run. Dataset/provider/purpose consent, recorded limits, current rights, owner-only decision training and protection-independent capacity are required. Inference access is not a learning grant. No local uploads, resume, streaming or publication.</p>
      {([["request_id", "Training request ID"], ["model_name", "Training model"], ["training_type", "Training method"], ["format_type", "Training format"], ["hf_dataset", "Registered remote dataset"], ["dataset", "Immutable batch ID"], ["run_id", "Training run ID"]] as const).map(([key, label]) => <label key={key} className="block text-sm">{label}<Input aria-label={label} value={training[key]} onChange={e => setTraining(previous => ({ ...previous, [key]: e.target.value }))} /></label>)}
      <label className="block text-sm">Decision training<select aria-label="Decision training" value={decision} onChange={e => setDecision(e.target.value)} className="ml-2 rounded bg-surface-card p-2"><option value="">As prepared (field omitted)</option><option value="true">Yes — Studio owner required</option><option value="false">No</option></select></label>
      <Button disabled={Object.values(training).some(value => !value)} onClick={() => {
        const body = { request_id: training.request_id, payload: { model_name: training.model_name, training_type: training.training_type, format_type: training.format_type, hf_dataset: training.hf_dataset, ...(decision ? { is_decision: decision === "true" } : {}) }, lineage: { dataset: training.dataset, run_id: training.run_id } };
        setConfirmation({ label: "Submit this prepared training request", body, run: () => startTraining(body, scope) });
      }}>Submit prepared training</Button>
      <Button disabled={!id || kind !== "training/jobs"} variant="outline" onClick={() => setConfirmation({ label: "Request cancellation — not proof of remote stop", body: { job_id: id }, run: () => controlTraining(id, "cancel", scope) })}>Request training cancellation</Button>
      <Button disabled={!id || (kind !== "training/jobs" && kind !== "adoptions")} variant="outline" onClick={() => setConfirmation({ label: "Reconcile this exact target — may pause dependent entries; never re-arm", body: { kind, id }, run: () => kind === "training/jobs" ? controlTraining(id, "reconcile", scope) : reconcileAdoption(id, scope) })}>Reconcile exact target</Button>
      <Button disabled variant="outline">Delete training data</Button>
      <p className="text-sm">No core deletion route is supported. Cancellation does not establish dataset deletion or trained-weight erasure.</p>
    </fieldset>
    <fieldset disabled={frozen} className="space-y-3 rounded border border-border-default p-3">
      <legend className="font-semibold">Qualified adoption and rollback</legend>
      <p className="text-sm">Only a pre-authorised role/run within unchanged risk limits is eligible. Core must verify independent evaluation, prospective evidence, current grant, staged serving identity, protection and handover. Rollback additionally requires a retained qualified target. This action never switches the global Live/Sandbox mode.</p>
      {([["request_id", "Adoption request ID"], ["run_id", "Target run ID"], ["role", "Target role"], ["candidate", "Candidate version ID"], ["expected_generation", "Expected run generation"]] as const).map(([key, label]) => <label key={key} className="block text-sm">{label}<Input aria-label={label} value={adoption[key]} onChange={e => setAdoption(previous => ({ ...previous, [key]: e.target.value }))} /></label>)}
      <label className="block text-sm">Adoption operation<select aria-label="Adoption operation" value={adoptionKind} onChange={e => setAdoptionKind(e.target.value)} className="ml-2 rounded bg-surface-card p-2"><option value="adopt">Adopt qualified candidate</option><option value="rollback">Rollback to retained candidate</option></select></label>
      <Button disabled={Object.values(adoption).some(value => !value)} onClick={() => {
        const body = { ...adoption, expected_generation: /^\d+$/.test(adoption.expected_generation) ? Number(adoption.expected_generation) : NaN, kind: adoptionKind };
        setConfirmation({ label: "Request the exact run-owned transition", body, run: () => adoptArtifact(body, scope) });
      }}>Request adoption or rollback</Button>
    </fieldset>
    {confirmation && <div role="alertdialog" aria-label="Confirm exact action" aria-describedby="testing-confirm-body" className="space-y-3 rounded border border-border-default p-3">
      <h3>{confirmation.label}</h3><pre id="testing-confirm-body" className="overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(confirmation.body, null, 2)}</pre>
      <p className="text-sm">This does not grant new authority. An uncertain outcome is never automatically resent.</p>
      <Button disabled={busy} onClick={() => { const action = confirmation; setConfirmation(null); void perform(action.run); }}>Confirm action</Button>
      <Button variant="outline" disabled={busy} onClick={() => setConfirmation(null)}>Keep unchanged</Button>
    </div>}
    {busy && <p aria-live="polite">Waiting for exact core readback…</p>}
    {error && <p role="alert" className="text-warning">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {backtestResult && <pre aria-label="Backtest result (not qualification)" className="overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(backtestResult, null, 2)}</pre>}
    {evidence && <pre aria-label="Exact core evidence" className="overflow-auto whitespace-pre-wrap break-all rounded border border-border-default p-3 text-xs">{JSON.stringify(evidence, null, 2)}</pre>}
  </section>;
}
