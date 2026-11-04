import { z } from "zod";
import { initialiseSchemaValidation } from "@/lib/schemaValidation";

initialiseSchemaValidation();

/** Account setup's current HTTP contract; no execution or read permission. */
export interface AccountRecoveryReference {
  broker: string;
  accountId: string;
  readOnly: true;
  writeAuthority: "none";
  grantAuthority: "none";
  reconciliationRequired: true;
  /** Publication-time owner census reference, never a current account book. */
  census: { complete: true; revision: string; runIds: string[] };
}
export interface AccountResultTarget { broker: string; accountId: string }
export type ManagedAccountResult = {
  receipt: {
    operationId: string;
    kind: "connect" | "reconnect";
    state: "committed" | "rejected" | "authentication_unknown" | "blocked";
    reason: string | null;
    credentialGeneration: number | null;
  };
} & (
  | { runtimeStatus: "session_present" | "session_unavailable" | "cleanup_pending" | "blocked"; recovery?: never }
  | { runtimeStatus: "read_only_recovery"; recovery: AccountRecoveryReference }
);
export interface LegacyConnectResult { connected: boolean; login: string }
export interface LegacyReloginResult {
  has_session: boolean;
  expires_at?: number | null;
  read_only?: boolean;
  login?: string;
}
export type AccountSessionResult = ManagedAccountResult | LegacyConnectResult | LegacyReloginResult;

export class NativeCredentialsRequired extends Error {}

/** Zod validates an own-key view without changing the returned DTO. Required
 * fields must be own properties; inherited unknown keys were never wire keys.
 * Optional legacy fields retain their existing property-lookup semantics. */
function strictOwnObject<T extends z.ZodRawShape>(shape: T, required = Object.keys(shape), forbidden: string[] = []) {
  return z.preprocess(value => {
    if (value === null || typeof value !== "object" || Array.isArray(value)
      || required.some(key => !Object.hasOwn(value, key))
      || forbidden.some(key => Object.hasOwn(value, key))) return null;
    const source = value as Record<string, unknown>;
    const entries = new Map(Object.keys(source).map(key => [key, source[key]]));
    for (const key of Object.keys(shape)) if (key in source) entries.set(key, source[key]);
    return Object.fromEntries(entries);
  }, z.strictObject(shape));
}

const ReceiptSchema = strictOwnObject({
  operationId: z.string(),
  kind: z.enum(["connect", "reconnect"]),
  state: z.enum(["committed", "rejected", "authentication_unknown", "blocked"]),
  reason: z.string().regex(/^[a-z][a-z0-9_]{0,63}$/).nullable(),
  credentialGeneration: z.number().refine(Number.isSafeInteger).min(1).nullable(),
});
// Preserve the old Array.some/Set contract even for non-JSON sparse arrays:
// a hole is not an explicitly supplied undefined leaf. No identifier is changed.
const RunIdsSchema = z.preprocess(
  value => {
    if (!Array.isArray(value)) return value;
    // Do not consult an input array's constructor/species while validating it.
    const ids = new Array<unknown>(value.length);
    for (let index = 0; index < value.length; index++) {
      if (index in value) ids[index] = value[index] === undefined ? null : value[index];
    }
    return ids;
  },
  z.array(z.string().min(1).optional()).min(1).refine(ids => new Set(ids).size === ids.length),
);
const RecoverySchema = strictOwnObject({
  broker: z.string().min(1),
  accountId: z.string().min(1),
  readOnly: z.literal(true),
  writeAuthority: z.literal("none"),
  grantAuthority: z.literal("none"),
  reconciliationRequired: z.literal(true),
  census: strictOwnObject({
    complete: z.literal(true),
    revision: z.string().regex(/^[0-9a-f]{64}$/),
    runIds: RunIdsSchema,
  }),
});
const ManagedResultSchema = z.union([
  strictOwnObject({
    receipt: ReceiptSchema,
    runtimeStatus: z.enum(["session_present", "session_unavailable", "cleanup_pending", "blocked"]),
  }, ["receipt", "runtimeStatus"], ["recovery"]),
  strictOwnObject({
    receipt: ReceiptSchema,
    runtimeStatus: z.literal("read_only_recovery"),
    recovery: RecoverySchema,
  }, ["receipt", "runtimeStatus"]),
]);
const LegacyConnectSchema = strictOwnObject({ connected: z.boolean(), login: z.string() });
const LegacyReloginSchema = strictOwnObject({
  session: strictOwnObject({
    has_session: z.boolean(),
    expires_at: z.number().nullable().optional(),
    read_only: z.boolean().optional(),
    login: z.string().optional(),
  }, ["has_session"]),
  login: z.string().optional(),
}, ["session"]);

function unavailable(): never {
  throw new Error("Account outcome unavailable — authentication may have occurred. Refresh account status; do not automatically retry or replace credentials.");
}

/** Bind durable operation and recovery target to the submitted request. Ordinary
 * receipts have no selector; never manufacture one from an account list. */
export function decodeManagedAccountResult(value: unknown, operationId: string, kind: "connect" | "reconnect", target?: AccountResultTarget): ManagedAccountResult {
  const parsed = ManagedResultSchema.safeParse(value);
  if (!parsed.success) return unavailable();
  const result = parsed.data;
  const r = result.receipt;
  if (r.operationId !== operationId || r.kind !== kind) return unavailable();
  if (result.runtimeStatus === "read_only_recovery"
    && (!target || result.recovery.broker !== target.broker || result.recovery.accountId !== target.accountId)) {
    return unavailable();
  }
  if (r.state === "committed") {
    if (r.credentialGeneration === null || result.runtimeStatus === "blocked") return unavailable();
  } else if (r.credentialGeneration !== null
    || (["authentication_unknown", "blocked"].includes(r.state)
      ? result.runtimeStatus !== "blocked"
      : !["session_unavailable", "cleanup_pending"].includes(result.runtimeStatus))) return unavailable();
  return value as ManagedAccountResult;
}
export function decodeConnectResult(value: unknown, key: string, target?: AccountResultTarget): ManagedAccountResult | LegacyConnectResult {
  const parsed = LegacyConnectSchema.safeParse(value);
  if (parsed.success) return parsed.data;
  return decodeManagedAccountResult(value, key, "connect", target);
}
export function decodeReloginResult(value: unknown, key: string, target?: AccountResultTarget): ManagedAccountResult | LegacyReloginResult {
  const parsed = LegacyReloginSchema.safeParse(value);
  if (parsed.success) {
    if (!parsed.data.session.has_session) {
      throw new NativeCredentialsRequired("Re-login did not establish a session — enter fresh credentials.");
    }
    return (value as { session: LegacyReloginResult }).session;
  }
  return decodeManagedAccountResult(value, key, "reconnect", target);
}
export function accountResultPresentation(result: AccountSessionResult): { sessionPresent: boolean; message: string } {
  if (!("receipt" in result)) {
    const present = "connected" in result ? result.connected : result.has_session;
    return { sessionPresent: present, message: present ? "Session present; not read completeness or trading authority." : "Session unavailable. Refresh account status." };
  }
  const { receipt, runtimeStatus } = result;
  if (runtimeStatus === "read_only_recovery") return {
    sessionPresent: true,
    message: `Account operation committed (including durable replay); read-only recovery for ${result.recovery.broker} / ${result.recovery.accountId}. Reconciliation required. No write or grant authority. Publication-time owner census reference only; not current books, flatness, or entry readiness.`,
  };
  const reason = receipt.reason ? ` Reason: ${receipt.reason}.` : "";
  if (receipt.state === "authentication_unknown") return { sessionPresent: false, message: `Authentication outcome unknown; blocked. Do not automatically retry or replace credentials.${reason}` };
  if (runtimeStatus === "blocked") return { sessionPresent: false, message: `Account operation blocked; no session availability established.${reason}` };
  const disposition = receipt.state === "committed" ? "Account operation committed (including durable replay)" : "Account operation rejected";
  if (runtimeStatus === "cleanup_pending") return { sessionPresent: false, message: `${disposition}; cleanup pending. Session availability is not established.${reason}` };
  if (runtimeStatus === "session_unavailable") return { sessionPresent: false, message: `${disposition}; current session unavailable. Refresh account status; this is not evidence that credentials are stale.${reason}` };
  return { sessionPresent: true, message: `${disposition}; session present, not read completeness or trading authority.` };
}
