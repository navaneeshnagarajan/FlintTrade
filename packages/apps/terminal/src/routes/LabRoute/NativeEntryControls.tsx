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
    expires_at_ms: Date.parse(value("expiry")),
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
  const field = (name: string, label: string, type = "text") => <div key={name} className="min-w-0">
    <Label htmlFor={`${prefix}-${name}`}>{label}</Label>
    <Input id={`${prefix}-${name}`} type={type} step={type === "datetime-local" ? 1 : undefined} value={value(name)} autoComplete="off"
      onChange={event => setDraft(previous => ({ ...previous, [name]: event.target.value }))} />
  </div>;
  return <section aria-label="Trading permission" className="min-w-0 space-y-3 border-t border-border-default pt-3">
    <h4 className="font-medium">Trading permission</h4>
    <p className="text-xs text-text-secondary">Preview, Accept, Grant and Start are separate steps.</p>
    <fieldset disabled={!enabled || busy || view.entry_state === "started"} className="grid min-w-0 gap-3 sm:grid-cols-2">
      <legend className="mb-2 text-sm">Entry limits</legend>
      {field("instrument", "Instrument ID")}{field("exchange", "Entry exchange")}{field("product", "Entry product")}
      {field("order", "Maximum order quantity")}{field("total", "Maximum total quantity")}
      {field("commands", "Maximum entry commands")}{field("reads", "Maximum entry reads")}
      {field("duration", "Duration (ms)")}{field("expiry", "Expires at (local time)", "datetime-local")}
      <Label className="flex items-center gap-2"><Checkbox checked={place}
        onChange={event => setPlace(event.target.checked)} />Allow new orders</Label>
      <Label className="flex items-center gap-2"><Checkbox checked={cancel}
        onChange={event => setCancel(event.target.checked)} />Allow cancelling open orders</Label>
    </fieldset>
    <p className="text-xs text-text-secondary">Limits are maximums. Every order still goes through the order checks.</p>
    {preview ? <p className="text-xs break-all">Preview {preview.preview_ref.id}. Max quantity: {preview.selection.limits.max_total_quantity}.
      Unconfirmed orders: {preview.duty.unknown_possible_writes ? "Yes" : "No"}.</p> : null}
    {transfer ? <p className="text-xs break-all">Accepted {transfer.transfer_ref.id} by {transfer.receiving_operator}.
      Reconcile first: {transfer.reconciliation_required ? "Yes" : "No"}.</p> : null}
    <div className="flex flex-wrap gap-2">
      <Button variant="outline" disabled={!enabled || busy || uncertain || !finite || view.entry_state === "started"}
        onClick={() => { if (parsed.success) void perform("Previewing limits", client => client.preview(view, parsed.data)); }}>Preview limits</Button>
      <Button variant="outline" disabled={!enabled || busy || uncertain || !selected || !!transfer}
        onClick={() => { if (preview) void perform("Accepting limits", client => client.accept(view, preview)); }}>Accept limits</Button>
      <Button variant="outline" disabled={!eligible || busy || !selected || !transfer || view.entry_state !== "ungranted"}
        onClick={() => { if (parsed.success) void perform("Granting permission", client => client.grant(view, parsed.data)); }}>Grant permission</Button>
      <Button variant="outline" disabled={!eligible || busy || view.entry_state !== "granted"
        || view.producer_state !== "not_started" || view.grant?.state !== "active" || view.grant.expires_at_ms <= Date.now()}
        onClick={() => void perform("Starting strategy", client => client.start(observation.session))}>Start strategy</Button>
    </div>
    <p className="text-xs text-text-secondary">Stop blocks new entries. Open orders and positions stay in place.</p>
  </section>;
}
