import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { onlineManager } from "@tanstack/react-query";
import { NativeEntryControls } from "./NativeEntryControls";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { isDemoAuthSession } from "@/services/ftApi.helpers";
import { nativeV2ConfigurationSchema, type NativeProjection, type NativeV2View } from "@/services/executionSessionNative";
import {
  createNativeV2Client, nativeStudioScopeKey, subscribeNativeStudioScope,
  type ExecutionSessionRecord, type NativeV2Observation,
} from "@/services/executionSessions";

function expiry(value: number) {
  const date = new Date(value * 1000);
  return Number.isFinite(date.getTime()) ? date.toISOString() : "Invalid date";
}

function modeLabel(environment: string) {
  return environment === "paper" ? "Practice" : "Live";
}

/** v1 observations only: no native activation, protection or broker actions. */
export function NativeExecutionInspection({ native }: { native: NativeProjection | undefined }) {
  if (!native) return <p>Run status unavailable. Read status again.</p>;
  const { binding, grant, qualification } = native;
  return <div className="space-y-3 text-sm min-w-0">
    <p className="break-all">Account: {binding.broker} / {binding.account_id} · Run {binding.run_id} · {modeLabel(binding.environment)}</p>
    <p className="break-all">Operator: {native.operator} · Source: {binding.actor}</p>
    <p className="break-all">Version: {native.revision}</p>
    <dl className="text-xs break-all">
      <dt>Strategy and settings versions</dt><dd>{binding.strategy_revision} / {binding.config_revision}</dd>
      <dt>Policy and provider versions</dt><dd>{binding.policy_revision} / {binding.provider_revision}</dd>
    </dl>
    <p>Requested: {grant ? grant.actions.join(", ") : "None"}</p>
    <p>Trading allowed: {native.authorised ? "Yes" : "No"}</p>
    <p>Ready: {native.native_ready ? "Yes" : "No"}</p>
    <p>Qualified: {native.qualified ? "Yes" : "No"}</p>
    <p>Qualification expiry: {qualification ? expiry(qualification.expires_at) : "None"}.</p>
    {qualification ? <p className="text-xs break-all">Evidence: {qualification.evidence_id} · {qualification.provenance}</p> : null}
    {grant ? <>
      <p>Grant {grant.grant_id}: {grant.revoked ? "Revoked" : "Not revoked"}. Expires {expiry(grant.expires_at)}. Session expires {expiry(grant.session_expires_at)}.</p>
      <p>Qualified until {expiry(grant.qualification.expires_at)}</p>
      <p>Limits: {grant.max_order_quantity} per order · {grant.max_total_quantity} total · ₹{grant.max_total_notional} notional · ₹{grant.max_loss} max loss · {grant.max_commands} orders</p>
      <p>Instruments: {grant.instruments.map(i => `${i.exchange}:${i.symbol}`).join(", ")}</p>
    </> : null}
    <p>Protection: {native.protection}. Stop entries leaves open orders and positions in place.</p>
    <h5 className="font-medium">Pending orders</h5>
    {native.obligations.length ? <ul aria-label="Pending orders" className="list-disc pl-5 break-all">
      {native.obligations.map(id => <li key={id}>{id}</li>)}
    </ul> : <p>No pending orders for this run.</p>}
    <h5 className="font-medium">Requests sent</h5>
    {native.commands.length ? <ul aria-label="Requests sent" className="space-y-2 break-all">
      {native.commands.map(command => <li key={command.command_id}>
        <p>{command.command_id} · {"operation" in command ? "Cancel" : "Place"} · {command.state} · {command.cause}</p>
        <p>Broker order: {command.broker_order_id ?? "Unconfirmed"} · Filled: {command.filled_quantity ?? "Unknown"}.</p>
        <p className="text-xs">History: {command.events.join(", ")}. Created {expiry(command.created_at)}{command.updated_at ? ` · Updated ${expiry(command.updated_at)}` : ""}</p>
      </li>)}
    </ul> : <p>No requests sent.</p>}
  </div>;
}

interface NativeStudioProps {
  sessions: ExecutionSessionRecord[];
  census: "loading" | "available" | "unavailable";
}

/** Selection retirement removes drafts, previous account evidence and errors together. */
export function NativeV2Studio(props: NativeStudioProps) {
  const key = useSyncExternalStore(subscribeNativeStudioScope, nativeStudioScopeKey, nativeStudioScopeKey);
  return <NativeStudioScope key={key} {...props} />;
}

const readSurfaces = ["orders", "positions", "holdings", "trades", "fees", "broker_protection", "quotes"] as const;

const referenceFields = [
  ["profile", "Operation profile"], ["policy", "Risk policy"],
  ["fees", "Fee policy"], ["custody", "Custody policy"],
] as const;

function NativeStudioScope({ sessions, census }: NativeStudioProps) {
  const prefix = useId();
  const clientRef = useRef<ReturnType<typeof createNativeV2Client> | null>(null);

  const auth = useAuthStore(state => state.status);
  const account = useBrokerStore(state => state.getActiveAccount());
  const online = onlineManager.isOnline();
  const enabled = auth === "logged-in" && !isDemoAuthSession() && account?.source === "native" && online;
  const canConfigure = enabled && account.status === "connected" && !account.read_only;
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [runId, setRunId] = useState("");
  const [surfaces, setSurfaces] = useState<Array<typeof readSurfaces[number]>>([]);
  const [observation, setObservation] = useState<NativeV2Observation | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const operation = useRef(0);
  const pending = useRef("");
  // Activity hide retires transient permissions and the transport owner, not
  // server custody. Returning requires an explicit read, never automatic Start.
  useEffect(() => () => {
    clientRef.current?.dispose(); clientRef.current = null;
    operation.current++; pending.current = "";
    setObservation(null); setDraft({}); setSurfaces([]); setRunId(""); setBusy(""); setError("");
  }, []);
  const value = (name: string) => draft[name] ?? "";
  const field = (name: string, label: string, type = "text") => <div className="min-w-0" key={name}>
    <Label htmlFor={`${prefix}-${name}`}>{label}</Label>
    <Input id={`${prefix}-${name}`} type={type} step={type === "datetime-local" ? 1 : undefined} value={value(name)} autoComplete="off"
      onChange={event => setDraft(previous => ({ ...previous, [name]: event.target.value }))} />
  </div>;
  const reference = (name: string) => ({ id: value(`${name}-id`), revision: value(`${name}-revision`) });
  const integer = (name: string) => /^[1-9][0-9]*$/.test(value(name)) ? Number(value(name)) : NaN;
  const money = (name: string) => ({ amount: value(name), currency: value("currency") });
  const request = () => {
    let producer: unknown;
    try { producer = JSON.parse(value("producer")); } catch { producer = null; }
    const options = value("profile-kind") === "2-options-1";
    return nativeV2ConfigurationSchema.safeParse({
      schema_version: value("profile-kind"),
      config: { run_id: value("run-id"), broker: account?.broker, account_id: account?.account_id,
        environment: "production", operation_profile_ref: reference("profile"), producer,
        risk: { policy_ref: reference("policy"), fee_policy_ref: reference("fees"),
          capital_cap: money("capital"), exposure_cap: money("exposure"), loss_action_threshold: money("loss"),
          max_mark_age_ms: integer("mark-age"),
          capital_basis: options ? "non_replenishing_long_premium_short_standalone_margin_plus_fees"
            : "non_replenishing_fee_inclusive_commitments",
          exposure_basis: options ? "gross_underlying_notional_no_cross_contract_netting_plus_liabilities"
            : "max_entry_cost_fresh_mark_plus_possible_fills_and_exit_fees",
          loss_basis: "run_lifetime_net_realised_plus_unrealised_after_fees",
          threshold_action: "latch_entry_retirement_and_broker_held_or_handback",
          ...(options ? { profile_version: "index_options_v1" } : {}),
        },
        custody: { policy_ref: reference("custody"), fallback: "receiving_operator_acceptance_before_entry",
          after_entry_retirement: "broker_held_or_operator_handback_no_agent_writes",
          global_kill: "blocks_all_agent_writes" },
      },
    });
  };
  const configuration = request();
  async function perform(label: string, action: (client: ReturnType<typeof createNativeV2Client>) => Promise<NativeV2Observation>) {
    if (pending.current && (label !== "Stopping entries" || pending.current === label)) return;
    pending.current = label;
    const client = clientRef.current ??= createNativeV2Client();
    const revision = ++operation.current;
    setBusy(label); setError("");
    try {
      const next = await action(client);
      if (client.isCurrent() && revision === operation.current) {
        setObservation(next); setRunId(next.view.scope.run_id);
      }
    } catch (reason) {
      if (client.isCurrent() && revision === operation.current) {
        setError(reason instanceof Error ? reason.message : "Result unknown. Read status.");
      }
    } finally {
      if (client.isCurrent() && revision === operation.current) { pending.current = ""; setBusy(""); }
    }
  }
  const listedRows = sessions.filter(row => row.autonomy_v2 && account?.source === "native"
    && row.autonomy_v2.scope.broker === account.broker && row.autonomy_v2.scope.account_id === account.account_id);
  const rows = observation && !listedRows.some(row => row.run_id === observation.session.run_id)
    ? [...listedRows, observation.session] : listedRows;
  const view = observation?.view;
  const deadline = Date.parse(value("read-deadline"));
  const canInspect = !!view && Number.isSafeInteger(integer("max-reads"))
    && Number.isSafeInteger(integer("max-pages")) && Number.isSafeInteger(deadline) && deadline > Date.now() && deadline - Date.now() <= 60_000;
  return <section aria-label="Native Studio" className="min-w-0 space-y-3 rounded border border-border-default p-3">
    <header className="space-y-1">
      <h3 className="text-base font-semibold">Native Studio</h3>
      <p className="text-sm text-text-secondary">Steps: Configure, Inspect, Qualify, Accept, Grant, Start.</p>
      <p className="text-xs break-all">Selected account: {account?.source === "native"
        ? `${account.broker} / ${account.account_id}.` : "None. Select a broker account."}</p>
    </header>
    {!online ? <p role="status">Offline. Reconnect, then read status.</p>
      : !enabled ? <p>Read-only. Sign in and select a broker account to edit.</p>
      : !canConfigure ? <p>Settings are read-only for this account.</p> : null}
    <form onSubmit={event => {
      event.preventDefault();
      if (!canConfigure || busy || !configuration.success) return;
      setRunId(configuration.data.config.run_id);
      void perform("Saving configuration", client => client.configure(configuration.data));
    }} className="space-y-3">
      <fieldset disabled={!canConfigure || !!busy} className="grid min-w-0 gap-3 sm:grid-cols-2">
        <legend className="mb-2 text-sm font-medium">Requested configuration</legend>
        {field("run-id", "Run ID")}
        <div><Label htmlFor={`${prefix}-profile-kind`}>Risk profile</Label>
          <select id={`${prefix}-profile-kind`} value={value("profile-kind")}
            className="w-full rounded border border-border-default bg-surface-base p-2 text-sm focus-visible:outline-2"
            onChange={event => setDraft(previous => ({ ...previous, "profile-kind": event.target.value }))}>
            <option value="">Choose a profile</option><option value="2">Cash</option>
            <option value="2-options-1">NIFTY and SENSEX options</option>
          </select>
        </div>
        {field("capital", "Capital limit")}{field("exposure", "Exposure limit")}
        {field("loss", "Loss limit")}{field("currency", "Currency")}
        {field("mark-age", "Max quote age (ms)")}
      </fieldset>
      <p className="text-xs text-text-secondary">Capital includes fees and is not topped up by profit.
        Options margin is counted per contract, without netting.</p>
      <details className="min-w-0">
        <summary className="cursor-pointer text-sm font-medium focus-visible:outline-2">Policy and strategy references</summary>
        <fieldset disabled={!canConfigure || !!busy} className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2">
          {referenceFields.flatMap(([name, label]) => [field(`${name}-id`, `${label} ID`),
            field(`${name}-revision`, `${label} version`)])}
          <div className="sm:col-span-2 min-w-0">
            <Label htmlFor={`${prefix}-producer`}>Strategy pin (JSON)</Label>
            <textarea id={`${prefix}-producer`} rows={4} value={value("producer")} autoComplete="off" spellCheck={false}
              className="w-full rounded border border-border-default bg-surface-base p-2 font-mono text-xs focus-visible:outline-2"
              onChange={event => setDraft(previous => ({ ...previous, producer: event.target.value }))} />
            <p className="text-xs text-text-secondary">Paste the strategy pin JSON, including model limits.</p>
          </div>
        </fieldset>
      </details>
      <Button type="submit" variant="outline" disabled={!canConfigure || !!busy || !configuration.success}>Save settings</Button>
      {!configuration.success ? <p className="text-xs text-text-secondary">Fill in every limit and reference.</p> : null}
    </form>
    <section aria-labelledby={`${prefix}-runs`} className="space-y-2 border-t border-border-default pt-3">
      <h4 id={`${prefix}-runs`} className="text-sm font-medium">Runs</h4>
      {census === "loading" ? <p role="status">Loading runs…</p>
        : census === "unavailable" ? <p>Runs unavailable. Refresh to try again.</p>
        : !rows.length ? <p className="text-xs">No runs for this account.</p> : null}
      <div className="flex flex-wrap gap-2">{rows.map(row => <Button key={row.run_id} variant="outline"
        disabled={!enabled || !!busy} onClick={() => {
          setRunId(row.run_id);
          if (row.autonomy_v2) setObservation({ session: row, view: row.autonomy_v2 });
          void perform("Reading status", client => client.read(row.run_id));
        }}>Inspect {row.run_id}</Button>)}</div>
      <Label htmlFor={`${prefix}-read-run`}>Run ID</Label>
      <Input id={`${prefix}-read-run`} value={runId} disabled={!!busy} onChange={event => {
        setRunId(event.target.value); setObservation(null); setError("");
      }} />
      <Button variant="outline" disabled={!enabled || !!busy || !runId}
        onClick={() => void perform("Reading status", client => client.read(runId))}>Read status</Button>
    </section>
    {busy ? <p role="status" className="text-sm">{busy} for {runId}.</p> : null}
    {error ? <p role="alert" className="break-words text-sm text-text-primary">{error}</p> : null}
    {view && observation ? <>
      <NativeV2Evidence view={view} generation={observation.session.generation} />
      <NativeEntryControls key={view.scope.run_id} observation={observation} enabled={canConfigure}
        busy={!!busy} uncertain={!!error} perform={perform} />
      <fieldset disabled={!enabled || !!busy} className="grid min-w-0 gap-3 sm:grid-cols-2">
        <legend className="mb-2 text-sm font-medium">Read limits</legend>
        {field("max-reads", "Max reads")}{field("max-pages", "Max pages")}
        {field("read-deadline", "Deadline (local time)", "datetime-local")}
      </fieldset>
      <fieldset disabled={!enabled || !!busy} className="flex flex-wrap gap-3">
        <legend className="mb-2 text-sm">Also read</legend>
        {readSurfaces.map(surface => <Label key={surface} className="flex items-center gap-2">
          <Checkbox aria-label={`Inspect ${surface}`} checked={surfaces.includes(surface)}
            onChange={event => setSurfaces(previous => event.target.checked
              ? [...previous, surface] : previous.filter(item => item !== surface))} />{surface.replaceAll("_", " ")}
        </Label>)}
      </fieldset>
      <p className="text-xs text-text-secondary">Selected reads share one read limit and a deadline of up to 60 seconds.</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={!enabled || !!busy || !canInspect} onClick={() => void perform(
          "Reading trades", client => client.inspect(view, { schema_version: "2", run_id: view.scope.run_id,
            expected_binding_revision: view.scope.binding_revision,
            read_plan: { surfaces: ["trades"], max_reads: integer("max-reads"), max_pages: integer("max-pages"),
              deadline_ms: deadline } }))}>Read trades</Button>
        <Button variant="outline" disabled={!enabled || !!busy || !canInspect || surfaces.length === 0}
          onClick={() => void perform("Reading selected", client => client.inspect(view, {
            schema_version: "2", run_id: view.scope.run_id, expected_binding_revision: view.scope.binding_revision,
            read_plan: { surfaces: [...surfaces], max_reads: integer("max-reads"), max_pages: integer("max-pages"), deadline_ms: deadline },
          }))}>Read selected</Button>
        <Button variant="outline" disabled={!enabled || !!busy}
          onClick={() => void perform("Checking qualification", client => client.qualify(view))}>Check qualification</Button>
        <Button variant="outline" disabled={!enabled || busy === "Stopping entries" || view.entry_state === "retired"}
          onClick={() => void perform("Stopping entries", client => client.stop(observation.session))}>Stop entries</Button>
      </div>
      <p className="text-xs text-text-secondary">Stop blocks new entries. Open orders and positions stay in place.</p>
    </> : null}
  </section>;
}

function NativeV2Evidence({ view, generation }: { view: NativeV2View; generation: number }) {
  const { scope, report, duty, config } = view;
  return <section aria-label="Run details" className="min-w-0 space-y-2 text-sm">
    <h4 className="font-medium break-all">{scope.run_id} · {view.schema_version === "2" ? "Cash" : "Index options"}</h4>
    <p className="text-xs break-all">{scope.broker} / {scope.account_id} · Generation {generation}</p>
    <p className="text-xs break-all">Operator: {scope.operator} · Source: {scope.actor}</p>
    <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-2 break-words text-xs">
      <dt>Requested</dt><dd>{view.requested_authority}</dd>
      <dt>Trading allowed</dt><dd>{view.effective_authority}</dd>
      <dt>Entry and strategy state</dt><dd>{view.entry_state} / {view.producer_state}</dd>
      <dt>Data age</dt><dd>{view.observation_freshness}</dd>
      <dt>Kill switch and loss limit</dt><dd>{view.global_kill ? "On" : "Off"} / {view.loss_threshold_latched ? "Hit" : "Not hit"}</dd>
      <dt>Capital, exposure and loss limits</dt><dd>{config.risk.capital_cap.amount} / {config.risk.exposure_cap.amount}
        {" / "}{config.risk.loss_action_threshold.amount} {config.risk.capital_cap.currency}</dd>
    </dl>
    <p>Qualification: {report?.status ?? "Not checked"}</p>
    {report ? <>
      <p className="text-xs break-all">Report {report.report_ref.id} · {report.report_ref.revision}</p>
      <p className="text-xs">Report expires {expiry(report.expires_at_ms / 1000)}</p>
      <ul aria-label="Qualification checks" className="space-y-1 text-xs break-words">
        {Object.entries(report.dimensions).map(([name, fact]) => <li key={name}>
          {name.replaceAll("_", " ")}: {fact.status} · {fact.provenance}
          {fact.evidence_ref ? <span className="break-all"> · {fact.evidence_ref.id} / {fact.evidence_ref.revision}</span> : " · no evidence"}
        </li>)}
      </ul>
      <p className="text-xs break-words">Blocking reasons: {report.blocking_reasons.join(", ") || "None"}.</p>
    </> : null}
    <h5 className="font-medium">Fills and open exposure</h5>
    {duty ? <>
      <p>Entry fills: {duty.cumulative_entry_fill} · Exit fills: {duty.cumulative_exit_fill} · Pending: {duty.possible_entry_quantity ?? "Unknown"}</p>
      <p>Unconfirmed orders: {duty.unknown_possible_writes ? "Yes" : "No"}</p>
      <ul className="text-xs break-all">{duty.obligations.map(row => <li key={row.obligation_id}>
        {row.obligation_id}: {row.kind} · Pending {row.possible_quantity ?? "Unknown"}</li>)}</ul>
    </> : <p>Fill and exposure data unavailable. Read status again.</p>}
    <p className="text-xs text-text-secondary">Grant: {view.grant?.state ?? "None"}. Mode: {modeLabel(scope.environment)}.</p>
  </section>;
}
