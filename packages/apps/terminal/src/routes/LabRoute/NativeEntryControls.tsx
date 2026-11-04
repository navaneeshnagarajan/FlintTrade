import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { GrantRequestV2Schema } from "@/generated/nativeAutonomyV2";
import { canonicalPolicy } from "@/services/runPolicyTransport";
import { type createNativeV2Client, type NativeV2Observation } from "@/services/executionSessions";

type Client = ReturnType<typeof createNativeV2Client>;
interface Props {
  observation: NativeV2Observation;
  enabled: boolean;
  busy: boolean;
  uncertain: boolean;
  perform: (label: string, action: (client: Client) => Promise<NativeV2Observation>) => Promise<void>;
}

/** Explicit finite intent only. The existing Core owners issue all authority. */
export function NativeEntryControls({ observation, enabled, busy, uncertain, perform }: Props) {
  const prefix = useId();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [place, setPlace] = useState(false);
  const [cancel, setCancel] = useState(false);
  const { view, preview, transfer } = observation;
  const value = (name: string) => draft[name] ?? "";
  const integer = (name: string) => /^[1-9][0-9]*$/.test(value(name)) ? Number(value(name)) : NaN;
  const parsed = GrantRequestV2Schema.safeParse({
    schema_version: "2", run_id: view.scope.run_id, expected_binding_revision: view.scope.binding_revision,
    report_ref: view.report?.report_ref, policy_ref: view.config.risk.policy_ref,
    expires_at_ms: integer("expiry"),
    limits: {
      instruments: [{ instrument_id: value("instrument"), exchange: value("exchange"), product: value("product") }],
      actions: [...(place ? ["place"] : []), ...(cancel ? ["cancel_unfilled"] : [])],
      max_order_quantity: integer("order"), max_total_quantity: integer("total"),
      max_commands: integer("commands"), max_reads: integer("reads"), max_duration_ms: integer("duration"),
    },
  });
  const finite = parsed.success && parsed.data.expires_at_ms > Date.now()
    && parsed.data.expires_at_ms - Date.now() <= parsed.data.limits.max_duration_ms;
  const selected = finite && preview && canonicalPolicy(preview.selection) === canonicalPolicy(parsed.data);
  const eligible = enabled && !uncertain && !view.global_kill && !view.loss_threshold_latched
    && view.report?.status === "eligible" && view.report.expires_at_ms > Date.now();
  const field = (name: string, label: string) => <div key={name} className="min-w-0">
    <Label htmlFor={`${prefix}-${name}`}>{label}</Label>
    <Input id={`${prefix}-${name}`} value={value(name)} autoComplete="off"
      onChange={event => setDraft(previous => ({ ...previous, [name]: event.target.value }))} />
  </div>;
  return <section aria-label="Finite native permission" className="min-w-0 space-y-3 border-t border-border-default pt-3">
    <h4 className="font-medium">Finite custody &amp; entry permission</h4>
    <p className="text-xs text-text-secondary">Preview, receiving acceptance, grant and Start are separate actions.
      A receiving acceptance keeps duties attributed; it neither clears exposure nor permits an account change.</p>
    <fieldset disabled={!enabled || busy || view.entry_state === "started"} className="grid min-w-0 gap-3 sm:grid-cols-2">
      <legend className="mb-2 text-sm">Operator-provided entry limits</legend>
      {field("instrument", "Entry instrument ID")}{field("exchange", "Entry exchange")}{field("product", "Entry product")}
      {field("order", "Maximum order quantity")}{field("total", "Maximum total quantity")}
      {field("commands", "Maximum entry commands")}{field("reads", "Maximum entry reads")}
      {field("duration", "Grant duration (ms)")}{field("expiry", "Grant expiry (epoch ms)")}
      <Label className="flex items-center gap-2"><Checkbox checked={place}
        onChange={event => setPlace(event.target.checked)} />Allow placement requests</Label>
      <Label className="flex items-center gap-2"><Checkbox checked={cancel}
        onChange={event => setCancel(event.target.checked)} />Allow cancellation of unfilled orders</Label>
    </fieldset>
    <p className="text-xs text-text-secondary">No numeric limits are preselected. Limits are requested ceilings, not remaining
      budget. Start may invoke the registered strategy or bounded model; every command still requires canonical admission.</p>
    {preview ? <p className="text-xs break-all">Preview: {preview.preview_ref.id} · duty {preview.duty.duty_ref.revision}.
      Finite maximum quantity: {preview.selection.limits.max_total_quantity}. Unknown possible writes: {String(preview.duty.unknown_possible_writes)}.</p> : null}
    {transfer ? <p className="text-xs break-all">Receiving acceptance: {transfer.transfer_ref.id} · {transfer.receiving_operator}.
      {" "}{transfer.outcome}. Reconciliation required: {String(transfer.reconciliation_required)}.</p> : null}
    <div className="flex flex-wrap gap-2">
      <Button variant="outline" disabled={!enabled || busy || uncertain || !finite || view.entry_state === "started"}
        onClick={() => { if (parsed.success) void perform("Previewing finite custody", client => client.preview(view, parsed.data)); }}>Preview finite custody</Button>
      <Button variant="outline" disabled={!enabled || busy || uncertain || !selected || !!transfer}
        onClick={() => { if (preview) void perform("Accepting finite custody", client => client.accept(view, preview)); }}>Accept finite custody</Button>
      <Button variant="outline" disabled={!eligible || busy || !selected || !transfer || view.entry_state !== "ungranted"}
        onClick={() => { if (parsed.success) void perform("Granting finite entry permission", client => client.grant(view, parsed.data)); }}>Grant finite entry permission</Button>
      <Button variant="outline" disabled={!eligible || busy || view.entry_state !== "granted"
        || view.producer_state !== "not_started" || view.grant?.state !== "active" || view.grant.expires_at_ms <= Date.now()}
        onClick={() => void perform("Starting native producer", client => client.start(observation.session))}>Start native producer</Button>
    </div>
    <p className="text-xs text-text-secondary">An acknowledgement is not a fill. Stop retires entry authority, not outstanding
      obligations or worker custody. Conversations never authorise these actions.</p>
  </section>;
}
