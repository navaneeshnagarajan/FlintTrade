import { z } from "zod";
import {
  ConfigureRequestV2Schema, OptionsConfigureRequestV2Schema, OptionsRunViewV2Schema, RunViewV2Schema,
  DutyViewV2Schema, GrantRequestV2Schema, RevisionRefV2Schema,
} from "@/generated/nativeAutonomyV2";

// The generated nominal variants retain their distinct cash/options policies.
export const nativeV2ConfigurationSchema = z.union([ConfigureRequestV2Schema, OptionsConfigureRequestV2Schema]);
export const nativeV2ViewSchema = z.union([RunViewV2Schema, OptionsRunViewV2Schema]);
export type NativeV2Configuration = z.infer<typeof nativeV2ConfigurationSchema>;
export type NativeV2View = z.infer<typeof nativeV2ViewSchema>;

// NativeCustodyV2.preview's public projection, not its private account pins.
export const nativeV2PreviewSchema = z.strictObject({
  preview_ref: RevisionRefV2Schema, selection: GrantRequestV2Schema, duty: DutyViewV2Schema,
}).refine(value => value.selection.run_id === value.duty.scope.run_id
  && value.selection.expected_binding_revision === value.duty.scope.binding_revision,
"Custody preview binding mismatch");
export type NativeV2Preview = z.infer<typeof nativeV2PreviewSchema>;

// Current v1 NativeAutonomy._public / command serializers. These are read
// observations, not a grant, a broker book, or the proposed v2 contract.
const Text = z.string().regex(/^[A-Za-z0-9_.:-]{1,128}$/);
const Digest = z.string().regex(/^[0-9a-f]{64}$/);
const Operator = z.string().regex(/^operator:[0-9a-f]{64}$/);
const Positive = z.number().finite().positive();
const Count = z.number().int().positive();
const BoundedActor = z.string().regex(/^bounded:[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/);
const Instrument = z.strictObject({ symbol: Text, exchange: z.enum(["NSE", "BSE"]) });
export const nativeConfigSchema = z.strictObject({
  run_id: Text, broker: z.string().regex(/^[a-z0-9][a-z0-9_-]{0,63}$/),
  account_id: Text.refine(value => /[A-Za-z0-9]/.test(value)), strategy_revision: Text,
  config_revision: Text, policy_revision: Text, provider_revision: Text,
});
const Binding = nativeConfigSchema.extend({ actor: BoundedActor, account: z.string().min(1), environment: z.literal("live") });
const Qualification = z.strictObject({
  binding_revision: Digest, runtime_fingerprint: Digest, evidence_id: Text, provenance: Text, expires_at: Positive,
});
const Grant = z.strictObject({
  grant_id: Text, expires_at: Positive, instruments: z.array(Instrument).min(1).max(20),
  actions: z.union([z.tuple([z.literal("place")]), z.tuple([z.literal("place"), z.literal("cancel")])]),
  max_order_quantity: Count, max_total_quantity: Count, max_total_notional: Positive,
  max_loss: Positive, max_commands: Count, operator: Operator, session_expires_at: Positive,
  binding_revision: Digest, qualification: Qualification, revoked: z.boolean(),
}).refine(g => g.max_order_quantity <= g.max_total_quantity && g.max_loss >= g.max_total_notional
  && g.expires_at <= g.session_expires_at, "Contradictory bounded grant");
const Order = Instrument.extend({
  action: z.literal("BUY"), product: z.literal("CNC"), order_type: z.literal("LIMIT"),
  quantity: Count, price: Positive, broker: Text, account_id: Text, strategy: BoundedActor,
});
const CommandState = z.enum(["pending_admission", "admitted", "dispatched", "acknowledged", "uncertain",
  "refused", "working", "partial", "filled", "cancel_requested", "settled", "reconciling"]);
const commandFields = {
  run_id: Text, command_id: Text, request_digest: Digest, source: z.string().regex(/^bounded:[0-9a-f]{64}$/),
  state: CommandState, cause: z.string().min(1), broker_order_id: z.string().min(1).nullable(),
  events: z.array(CommandState).min(1), created_at: Positive, updated_at: Positive.optional(),
  filled_quantity: z.number().int().nonnegative().optional(),
};
const Command = z.union([
  z.strictObject({ ...commandFields, body: Order, quantity: Count,
    notional: z.string().regex(/^\d+(?:\.\d+)?(?:E[+-]?\d+)?$/) }),
  z.strictObject({ ...commandFields, operation: z.literal("cancel"), placement_command_id: Text,
    body: z.strictObject({ _op: z.literal("cancel"), order_id: z.string().min(1) }),
    expected_order: Order, quantity: z.literal(0), notional: z.literal("0") }),
]);
export const nativeProjectionSchema = z.strictObject({
  binding: Binding, operator: Operator, revision: Digest,
  state: z.enum(["configured", "qualified", "authorised", "entries_stopped", "reconciliation_required"]),
  qualification: Qualification.nullable(), grant: Grant.nullable(), configured: z.literal(true),
  qualified: z.boolean(), authorised: z.boolean(), native_ready: z.boolean(), commands: z.array(Command),
  admission_reason: z.enum(["current_grant_and_qualification_required", "kill_switch_latched", "safety_runtime_unavailable",
    "reconciliation_required", "canonical_admission_required"]),
  obligations: z.array(Text), protection: z.enum(["operator_handback_required", "not_granted"]),
  admission_required: z.literal(true), qualification_reason: z.enum(["current_server_evidence", "server_qualification_required"]),
}).superRefine((row, ctx) => {
  const reject = (message: string) => ctx.addIssue({ code: "custom", message });
  const { binding, grant, qualification } = row;
  if (binding.account !== `${binding.broker}:${binding.account_id}` || binding.actor !== `bounded:${binding.run_id}`) reject("Native binding identity mismatch");
  if (qualification && qualification.binding_revision !== row.revision) reject("Qualification binding mismatch");
  if (grant && (grant.operator !== row.operator || grant.binding_revision !== row.revision
    || grant.qualification.binding_revision !== row.revision)) reject("Grant identity mismatch");
  if (row.qualified && !qualification) reject("Qualified without evidence");
  if (row.state === "configured" && (row.qualified || row.authorised || qualification || grant)) reject("Configured state has authority evidence");
  if (row.authorised && row.state !== "authorised" && row.state !== "qualified") reject("Stopped or recovering run reports effective authority");
  if (row.qualification_reason !== (row.qualified ? "current_server_evidence" : "server_qualification_required")) reject("Qualification reason mismatch");
  if (row.authorised && (!row.qualified || !grant || grant.revoked || !qualification
    || qualification.binding_revision !== grant.qualification.binding_revision
    || qualification.runtime_fingerprint !== grant.qualification.runtime_fingerprint
    || qualification.evidence_id !== grant.qualification.evidence_id
    || qualification.provenance !== grant.qualification.provenance
    || qualification.expires_at !== grant.qualification.expires_at)) reject("Contradictory effective authority");
  const hasObligations = row.obligations.length > 0;
  if (row.native_ready !== (row.authorised && !hasObligations)) reject("Native readiness mismatch");
  if (row.protection !== (hasObligations ? "operator_handback_required" : "not_granted")) reject("Obligation protection mismatch");
  const effectiveReason = hasObligations ? "reconciliation_required" : "canonical_admission_required";
  if (row.authorised ? row.admission_reason !== effectiveReason
    : ["canonical_admission_required", "reconciliation_required"].includes(row.admission_reason)) reject("Admission reason mismatch");
  if (["kill_switch_latched", "safety_runtime_unavailable"].includes(row.admission_reason)
    && (!row.qualified || !grant || grant.revoked)) reject("Safety blocker without current authority");
  if (row.admission_reason === "kill_switch_latched" && row.state !== "entries_stopped") reject("Kill state mismatch");
  const ids = row.commands.map(c => c.command_id);
  const obligations = row.commands.filter(c => c.state !== "settled" && c.state !== "refused").map(c => c.command_id);
  if (new Set(ids).size !== ids.length || new Set(row.obligations).size !== row.obligations.length
    || obligations.length !== row.obligations.length || obligations.some(id => !row.obligations.includes(id))) reject("Incomplete command obligation census");
  for (const command of row.commands) {
    const order = "expected_order" in command ? command.expected_order : command.body;
    if (!grant || command.run_id !== binding.run_id || order.broker !== binding.broker
      || order.account_id !== binding.account_id || order.strategy !== binding.actor) reject("Command binding mismatch");
    if ("operation" in command) {
      const placement = row.commands.find(c => c.command_id === command.placement_command_id);
      if (!placement || "operation" in placement || command.body.order_id !== command.broker_order_id
        || placement.broker_order_id !== command.broker_order_id
        || Order.keyof().options.some(field => command.expected_order[field] !== placement.body[field])) {
        reject("Cancellation receipt identity mismatch");
      }
    } else if (command.quantity !== order.quantity) reject("Command quantity mismatch");
    if ((command.filled_quantity ?? 0) > order.quantity) reject("Command fill exceeds quantity");
    if ((command.state === "settled" || command.state === "refused") && (command.filled_quantity ?? 0) > 0) reject("Known fills remain unresolved");
    if (command.state === "settled" && (command.filled_quantity !== 0 || !command.broker_order_id)) reject("Settlement observation incomplete");
  }
});
export type NativeProjection = z.infer<typeof nativeProjectionSchema>;
