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
  return Number.isFinite(date.getTime()) ? date.toISOString() : `${value} epoch seconds (outside browser date range)`;
}

/** v1 observations only: no native activation, protection or broker actions. */
export function NativeExecutionInspection({ native }: { native: NativeProjection | undefined }) {
  if (!native) return <p>Native authority unavailable — no structured projection. No readiness, retirement or broker-flatness claim can be made.</p>;
  const { binding, grant, qualification } = native;
  return <div className="space-y-3 text-sm min-w-0">
    <p className="break-all">Immutable target: {binding.broker} / {binding.account_id} · run {binding.run_id} · {binding.environment}</p>
    <p className="break-all">Operator: {native.operator} · Bounded actor: {binding.actor}</p>
    <p className="break-all">Binding revision: {native.revision}</p>
    <dl className="text-xs break-all">
      <dt>Strategy / configuration revisions</dt><dd>{binding.strategy_revision} / {binding.config_revision}</dd>
      <dt>Policy / provider revisions</dt><dd>{binding.policy_revision} / {binding.provider_revision}</dd>
    </dl>
    <p>Requested authority: {grant ? grant.actions.join(", ") : "no grant recorded"}.</p>
    <p>Effective entry authority: {native.authorised ? "authorised" : "not authorised"} at the last Core observation. Admission reason: {native.admission_reason}.</p>
    <p>Native readiness reported by Core: {native.native_ready ? "ready for canonical admission" : "not ready"}. Each command still requires canonical admission; this view grants no permission.</p>
    <p>Qualification: {native.qualified ? "current server evidence" : "not current"} · {native.qualification_reason}.</p>
    <p>Qualification expiry: {qualification ? expiry(qualification.expires_at) : "no current qualification recorded"}.</p>
    {qualification ? <p className="text-xs break-all">Evidence: {qualification.evidence_id} · {qualification.provenance} · runtime {qualification.runtime_fingerprint}</p> : null}
    {grant ? <>
      <p>Grant {grant.grant_id}: {grant.revoked ? "revoked" : "not marked revoked"}. Grant expiry: {expiry(grant.expires_at)}. Operator session expiry: {expiry(grant.session_expires_at)}.</p>
      <p>Grant-bound qualification expiry: {expiry(grant.qualification.expires_at)}. This retained evidence does not establish current qualification.</p>
      <p>Recorded limits: {grant.max_order_quantity} per order · {grant.max_total_quantity} total quantity · {grant.max_total_notional} total notional · {grant.max_loss} loss bound · {grant.max_commands} commands. These are grant observations, not available budget or a new protection policy.</p>
      <p>Instruments: {grant.instruments.map(i => `${i.exchange}:${i.symbol}`).join(", ")}</p>
    </> : null}
    <p>Protection observation: {native.protection}. Stop entries does not cancel orders or close positions; an acknowledgement or stopped run is not proof of broker flatness.</p>
    <h5 className="font-medium">Unresolved obligations</h5>
    {native.obligations.length ? <ul aria-label="Unresolved obligations" className="list-disc pl-5 break-all">
      {native.obligations.map(id => <li key={id}>{id}</li>)}
    </ul> : <p>No unresolved command obligations reported. This is not a complete account book or proof of zero exposure.</p>}
    <h5 className="font-medium">Command receipts</h5>
    {native.commands.length ? <ul aria-label="Command receipts" className="space-y-2 break-all">
      {native.commands.map(command => <li key={command.command_id}>
        <p>{command.command_id} · {"operation" in command ? "cancel request" : "placement request"} · {command.state} · {command.cause}</p>
        <p>Broker order: {command.broker_order_id ?? "not confirmed"} · observed filled quantity: {command.filled_quantity ?? "not observed"}.</p>
        <p className="text-xs">Receipt history: {command.events.join(" → ")}. Created: {expiry(command.created_at)}{command.updated_at ? ` · Updated: ${expiry(command.updated_at)}` : ""}</p>
      </li>)}
    </ul> : <p>No command receipts reported.</p>}
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
        setError(reason instanceof Error ? reason.message : "Native outcome unavailable; read exact status.");
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
      <p className="text-sm text-text-secondary">Configure → inspect → qualify → accept custody → grant → Start.</p>
      <p className="text-xs text-text-secondary">Configuration is intent, not permission. No automatic Live switch or Start.
        Provider evidence must qualify independently; an empty duty census never grants permission.</p>
      <p className="text-xs break-all">Selected account: {account?.source === "native"
        ? `${account.broker} / ${account.account_id}` : "select a native account in the account selector"}.</p>
    </header>
    {!online ? <p role="status">Offline — previous observations are not current. Reconnect and read exact status.</p>
      : !enabled ? <p>Read-only: an installed operator session and selected native account are required.</p>
      : !canConfigure ? <p>Configuration is read-only. Exact inspection and entry retirement remain separate.</p> : null}
    <form onSubmit={event => {
      event.preventDefault();
      if (!canConfigure || busy || !configuration.success) return;
      setRunId(configuration.data.config.run_id);
      void perform("Saving configuration", client => client.configure(configuration.data));
    }} className="space-y-3">
      <fieldset disabled={!canConfigure || !!busy} className="grid min-w-0 gap-3 sm:grid-cols-2">
        <legend className="mb-2 text-sm font-medium">Requested configuration</legend>
        {field("run-id", "New run ID")}
        <div><Label htmlFor={`${prefix}-profile-kind`}>Risk profile</Label>
          <select id={`${prefix}-profile-kind`} value={value("profile-kind")}
            className="w-full rounded border border-border-default bg-surface-base p-2 text-sm focus-visible:outline-2"
            onChange={event => setDraft(previous => ({ ...previous, "profile-kind": event.target.value }))}>
            <option value="">Choose a profile</option><option value="2">Cash — separate v2 policy</option>
            <option value="2-options-1">Nifty / Sensex index options</option>
          </select>
        </div>
        {field("capital", "Capital cap")}{field("exposure", "Exposure cap")}
        {field("loss", "Loss action threshold")}{field("currency", "Currency")}
        {field("mark-age", "Maximum mark age (ms)")}
      </fieldset>
      <p className="text-xs text-text-secondary">Limits stay blank until entered. Capital is non-replenishing and fee-inclusive;
        options use standalone short margin and gross notional without cross-contract netting.
        Profit is not new capital. This is not an uncovered-short loss guarantee. No quantity or expiry permission is issued.</p>
      <details className="min-w-0">
        <summary className="cursor-pointer text-sm font-medium focus-visible:outline-2">Required policy and producer references</summary>
        <fieldset disabled={!canConfigure || !!busy} className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2">
          {referenceFields.flatMap(([name, label]) => [field(`${name}-id`, `${label} ID`),
            field(`${name}-revision`, `${label} revision (SHA-256)`)])}
          <div className="sm:col-span-2 min-w-0">
            <Label htmlFor={`${prefix}-producer`}>Exact producer pin (JSON)</Label>
            <textarea id={`${prefix}-producer`} rows={4} value={value("producer")} autoComplete="off" spellCheck={false}
              className="w-full rounded border border-border-default bg-surface-base p-2 font-mono text-xs focus-visible:outline-2"
              onChange={event => setDraft(previous => ({ ...previous, producer: event.target.value }))} />
            <p className="text-xs text-text-secondary">Enter the reviewed ProducerPinV2, including explicit model limits if applicable.
              References do not establish installation, tariffs, history completeness or provider acceptance.</p>
          </div>
        </fieldset>
      </details>
      <Button type="submit" variant="outline" disabled={!canConfigure || !!busy || !configuration.success}>Save native configuration</Button>
      {!configuration.success ? <p className="text-xs text-text-secondary">Complete every limit and required reference using the exact generated contract; no numeric coercion or permission defaults.</p> : null}
    </form>
    <div className="space-y-2 border-t border-border-default pt-3">
      <h4 className="text-sm font-medium">Runs &amp; evidence</h4>
      {census === "loading" ? <p role="status">Loading native run identities…</p>
        : census === "unavailable" ? <p>Native run census unavailable — not an empty or settled book.</p>
        : !rows.length ? <p className="text-xs">No native v2 runs in this selected-account census. Outstanding custody is not established by this list.</p> : null}
      <div className="flex flex-wrap gap-2">{rows.map(row => <Button key={row.run_id} variant="outline"
        disabled={!enabled || !!busy} onClick={() => {
          setRunId(row.run_id);
          if (row.autonomy_v2) setObservation({ session: row, view: row.autonomy_v2 });
          void perform("Reading exact status", client => client.read(row.run_id));
        }}>Inspect {row.run_id}</Button>)}</div>
      <Label htmlFor={`${prefix}-read-run`}>Exact native run ID</Label>
      <Input id={`${prefix}-read-run`} value={runId} disabled={!!busy} onChange={event => {
        setRunId(event.target.value); setObservation(null); setError("");
      }} />
      <Button variant="outline" disabled={!enabled || !!busy || !runId}
        onClick={() => void perform("Reading exact status", client => client.read(runId))}>Read exact native status</Button>
    </div>
    {busy ? <p role="status" className="text-sm">{busy} — {runId}. No automatic resend.</p> : null}
    {error ? <p role="alert" className="break-words text-sm text-text-primary">{error} Last-known evidence is not current.</p> : null}
    {view && observation ? <>
      <NativeV2Evidence view={view} generation={observation.session.generation} />
      <NativeEntryControls key={view.scope.run_id} observation={observation} enabled={canConfigure}
        busy={!!busy} uncertain={!!error} perform={perform} />
      <fieldset disabled={!enabled || !!busy} className="grid min-w-0 gap-3 sm:grid-cols-2">
        <legend className="mb-2 text-sm font-medium">Explicit finite inspection budget</legend>
        {field("max-reads", "Maximum inspection reads")}{field("max-pages", "Maximum inspection pages")}
        {field("read-deadline", "Inspection deadline (local time)", "datetime-local")}
      </fieldset>
      <fieldset disabled={!enabled || !!busy} className="flex flex-wrap gap-3">
        <legend className="mb-2 text-sm">Explicit additional read selection</legend>
        {readSurfaces.map(surface => <Label key={surface} className="flex items-center gap-2">
          <Checkbox aria-label={`Inspect ${surface}`} checked={surfaces.includes(surface)}
            onChange={event => setSurfaces(previous => event.target.checked
              ? [...previous, surface] : previous.filter(item => item !== surface))} />{surface.replaceAll("_", " ")}
        </Label>)}
      </fieldset>
      <p className="text-xs text-text-secondary">All selected surfaces share the existing canonical owner's finite read/page budget and deadline within 60 seconds.
        Missing fee windows or quote instruments remain unavailable; no selections are guessed. Daily trades do not establish lifetime completeness.
        Qualification evaluates current server-held evidence with an empty request; it performs no implicit provider refresh.</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={!enabled || !!busy || !canInspect} onClick={() => void perform(
          "Inspecting bounded trades", client => client.inspect(view, { schema_version: "2", run_id: view.scope.run_id,
            expected_binding_revision: view.scope.binding_revision,
            read_plan: { surfaces: ["trades"], max_reads: integer("max-reads"), max_pages: integer("max-pages"),
              deadline_ms: deadline } }))}>Inspect trades</Button>
        <Button variant="outline" disabled={!enabled || !!busy || !canInspect || surfaces.length === 0}
          onClick={() => void perform("Inspecting selected surfaces", client => client.inspect(view, {
            schema_version: "2", run_id: view.scope.run_id, expected_binding_revision: view.scope.binding_revision,
            read_plan: { surfaces: [...surfaces], max_reads: integer("max-reads"), max_pages: integer("max-pages"), deadline_ms: deadline },
          }))}>Inspect selected surfaces</Button>
        <Button variant="outline" disabled={!enabled || !!busy}
          onClick={() => void perform("Evaluating qualification", client => client.qualify(view))}>Evaluate qualification</Button>
        <Button variant="outline" disabled={!enabled || busy === "Stopping entries" || view.entry_state === "retired"}
          onClick={() => void perform("Stopping entries", client => client.stop(observation.session))}>Stop native entries</Button>
      </div>
      <p className="text-xs text-text-secondary">Stop remains available with stale entry evidence. It retires future agent writes;
        it does not cancel exchange orders, liquidate positions or confirm settlement. A generation conflict requires exact readback.</p>
    </> : null}
  </section>;
}

function NativeV2Evidence({ view, generation }: { view: NativeV2View; generation: number }) {
  const { scope, report, duty, config } = view;
  return <section aria-label="Native run evidence" className="min-w-0 space-y-2 text-sm">
    <h4 className="font-medium break-all">{scope.run_id} · {view.schema_version === "2" ? "Cash" : "Index options"}</h4>
    <p className="text-xs break-all">{scope.broker} / {scope.account_id} · generation {generation} · binding {scope.binding_revision}</p>
    <p className="text-xs break-all">Authenticated operator: {scope.operator} · bounded producer: {scope.actor}</p>
    <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-2 break-words text-xs">
      <dt>Requested authority</dt><dd>{view.requested_authority}</dd>
      <dt>Effective authority (last Core observation)</dt><dd>{view.effective_authority}</dd>
      <dt>Entry / producer state</dt><dd>{view.entry_state} / {view.producer_state}</dd>
      <dt>Observation freshness (at last read)</dt><dd>{view.observation_freshness}</dd>
      <dt>Global kill / loss latch</dt><dd>{String(view.global_kill)} / {String(view.loss_threshold_latched)}</dd>
      <dt>Recorded capital / exposure / loss limits</dt><dd>{config.risk.capital_cap.amount} / {config.risk.exposure_cap.amount}
        {" / "}{config.risk.loss_action_threshold.amount} {config.risk.capital_cap.currency}</dd>
    </dl>
    <p>Qualification: {report?.status ?? "not evaluated"}. A report never grants entry authority.</p>
    {report ? <>
      <p className="text-xs break-all">Report {report.report_ref.id} · {report.report_ref.revision}</p>
      <p className="text-xs">Report expiry: {expiry(report.expires_at_ms / 1000)}. Time and account freshness must still be checked.</p>
      <ul aria-label="Qualification dimensions" className="space-y-1 text-xs break-words">
        {Object.entries(report.dimensions).map(([name, fact]) => <li key={name}>
          {name.replaceAll("_", " ")}: {fact.status} · {fact.provenance}
          {fact.evidence_ref ? <span className="break-all"> · {fact.evidence_ref.id} / {fact.evidence_ref.revision}</span> : " · no evidence reference"}
        </li>)}
      </ul>
      <p className="text-xs break-words">Blocking reasons: {report.blocking_reasons.join(", ") || "none reported — not a grant"}.</p>
    </> : null}
    <h5 className="font-medium">Known fills &amp; outstanding custody</h5>
    {duty ? <>
      <p>Known cumulative entry fills: {duty.cumulative_entry_fill} · exit fills: {duty.cumulative_exit_fill}.
        Possible entry quantity: {duty.possible_entry_quantity ?? "unknown"}.</p>
      <p>Custody: {duty.custody} · {duty.state} · coverage {duty.coverage}.
        Unknown possible writes: {String(duty.unknown_possible_writes)}.</p>
      <ul className="text-xs break-all">{duty.obligations.map(row => <li key={row.obligation_id}>
        {row.obligation_id}: {row.kind} · possible quantity {row.possible_quantity ?? "unknown"}</li>)}</ul>
    </> : <p>No duty projection is supplied. Known fills and outstanding account exposure are not established;
      this is not a zero-exposure census or pre-entry consent.</p>}
    <p className="text-xs text-text-secondary">Grant: {view.grant?.state ?? "none recorded"}. Environment: {scope.environment}.
      Synthetic evidence proves engineering mechanics only, not provider eligibility. Conversations propose; they never authorise.</p>
  </section>;
}

