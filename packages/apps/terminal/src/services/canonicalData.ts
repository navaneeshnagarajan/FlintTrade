import { useSyncExternalStore } from "react";
import { onlineManager } from "@tanstack/react-query";
import { z } from "zod";
import { buildHeaders, getBase, isDemoAuthSession } from "./ftApi.helpers";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { captureOperatorIncidentScope, isOperatorIncidentScopeCurrent } from "@/lib/operatorIncidentScope";

const text = z.string().min(1).max(256).refine(value => value === value.trim());
const hash = z.string().regex(/^[a-f0-9]{64}$/);
const integer = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const time = z.string().regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/).refine(value => z.iso.datetime({ offset: true }).safeParse(value).success);
const decimal = z.string().max(128).regex(/^-?\d+(?:\.\d+)?(?:E[+-]?\d+)?$/);
const scopeSchema = z.object({ principal_id: text, environment: text, account_id: text.nullable(), run_id: text.nullable(), generation: integer });
export type DataScope = z.infer<typeof scopeSchema>;
const identitySchema = z.looseObject({ instrument_id: text, venue: text, asset_class: text, currency: text, quantity_unit: text, price_unit: text, adjustment: text, calendar_id: text, calendar_revision: text, interval_seconds: integer.positive(), multiplier: decimal });
const sourceSchema = z.object({ connection_id: text, provider: text, environment: text, account_id: text.nullable(), auth_generation: integer, configuration_generation: integer });
const coverageSchema = z.object({ expected: integer, observed: integer, missing: z.array(time) });
const datasetSchema = z.discriminatedUnion("source_kind", [
  z.object({ source_kind: z.literal("recorded_history"), dataset_id: text, snapshot_id: hash, label: text, identity: identitySchema, coverage: coverageSchema, status: z.enum(["available", "partial", "unavailable"]), execution_authority: z.literal(false) }),
  z.object({ source_kind: z.literal("native"), dataset_id: text, label: text, status: z.literal("unavailable"), reason: text, execution_authority: z.literal(false) }),
]);
const catalogueSchema = z.object({ scope: scopeSchema, datasets: z.array(datasetSchema), legacy_history: z.literal("unqualified_legacy"), portfolio: text });
export type Dataset = z.infer<typeof datasetSchema>;
const frameSchema = z.object({ sequence: integer, kind: z.enum(["snapshot", "update"]), observed_at: time, published_at: time.nullable().optional(), retrieved_at: time, payload: z.unknown() });
const leaseSnapshotSchema = z.object({ dataset_id: text, identity: identitySchema, source: sourceSchema, scope: scopeSchema, policy_revision: text, status: z.enum(["fresh", "stale", "unavailable"]), reason: z.string(), age_seconds: z.number().finite().nonnegative().nullable(), expires_at: z.number().finite(), sequence: integer.nullable(), observed_at: time.nullable(), published_at: time.nullable(), retrieved_at: time.nullable(), payload: z.unknown(), updates: z.array(frameSchema), replay_gap: z.boolean() });
export type LeaseSnapshot = z.infer<typeof leaseSnapshotSchema>;
export interface DatasetLease { lease_id: string; snapshot: LeaseSnapshot }
const barSchema = z.looseObject({ timestamp: time, open: z.number().finite().positive(), high: z.number().finite().positive(), low: z.number().finite().positive(), close: z.number().finite().positive(), volume: z.number().finite().nonnegative().nullable(), oi: z.number().finite().nonnegative().nullable(), published_at: time.nullable() });
const manifestSchema = z.looseObject({
  schema_version: z.literal(1), snapshot_id: hash, identity: identitySchema, scope: scopeSchema,
  policy: z.looseObject({ mode: z.enum(["single", "priority_fill_gaps"]), duplicates: z.literal("identical_only"), conflicts: z.enum(["reject", "prefer_priority"]), revision: text, priority: z.array(text).min(1), sessions: z.array(z.object({ start: time, end: time })).min(1) }),
  contributors: z.array(z.looseObject({ source: sourceSchema, identity: identitySchema, revision: text, status: z.enum(["available", "partial", "unavailable"]), retrieved_at: time, bars: z.array(barSchema) })),
  bars: z.array(barSchema.extend({ source_id: text, source_revision: text, retrieved_at: time })),
  status: z.enum(["available", "partial", "unavailable"]), coverage: coverageSchema,
  duplicates: z.record(z.string(), integer), conflicts: z.array(z.object({ timestamp: time, selected_source: text, other_source: text, selected_hash: hash, other_hash: hash })),
  rights: z.literal("not_attested"), execution_authority: z.literal(false),
});
export type HistoryManifest = z.infer<typeof manifestSchema>;
function validateHistory(raw: unknown): HistoryManifest {
  const value = manifestSchema.parse(raw);
  const invalid = () => { throw new CanonicalDataError("Invalid or inconsistent immutable history manifest."); };
  const { coverage, contributors, bars, policy } = value;
  if (coverage.observed !== bars.length || coverage.expected !== coverage.observed + coverage.missing.length || new Set(coverage.missing).size !== coverage.missing.length) invalid();
  if (new Set(policy.priority).size !== policy.priority.length || !same(policy.priority, contributors.map(part => part.source.connection_id)) || (policy.mode === "single" && policy.priority.length !== 1)) invalid();
  const coherent = (bar: z.infer<typeof barSchema>) => bar.low <= Math.min(bar.open, bar.close) && Math.max(bar.open, bar.close) <= bar.high;
  for (const part of contributors) {
    if (!same(part.identity, value.identity) || (part.status === "unavailable" && part.bars.length) || part.bars.some(bar => !coherent(bar))) invalid();
  }
  const partitions = new Map(contributors.map(part => [part.source.connection_id, { part, rows: new Map(part.bars.map(bar => [bar.timestamp, bar])) }]));
  let previous: string | null = null;
  for (const bar of bars) {
    if (!coherent(bar) || (previous !== null && normaliseTime(bar.timestamp) <= previous) || coverage.missing.includes(bar.timestamp)) invalid();
    previous = normaliseTime(bar.timestamp);
    const partition = partitions.get(bar.source_id);
    const original = partition?.rows.get(bar.timestamp);
    if (!partition || !original || partition.part.revision !== bar.source_revision || bar.retrieved_at !== partition.part.retrieved_at || ["timestamp", "open", "high", "low", "close", "volume", "oi", "published_at"].some(key => !same(original[key], bar[key]))) invalid();
  }
  const status = !bars.length ? "unavailable" : !coverage.missing.length && contributors.every(part => part.status === "available") ? "available" : "partial";
  if (value.status !== status) invalid();
  return value;
}
function validateSnapshot(raw: unknown): LeaseSnapshot {
  const value = leaseSnapshotSchema.parse(raw);
  const invalid = () => { throw new CanonicalDataError("Invalid or incomplete dataset snapshot."); };
  if (value.sequence === null) {
    if (value.status !== "unavailable" || value.age_seconds !== null || value.observed_at !== null || value.retrieved_at !== null || value.published_at !== null || value.payload !== null || value.updates.length) invalid();
  } else {
    if (value.status === "unavailable" || value.age_seconds === null || value.observed_at === null || value.retrieved_at === null || value.payload === undefined || Date.parse(value.observed_at) > Date.parse(value.retrieved_at)) invalid();
    if (value.dataset_id.startsWith("history:")) {
      const manifest = validateHistory(value.payload);
      if (value.dataset_id !== `history:${manifest.snapshot_id}` || value.policy_revision !== manifest.snapshot_id || !same(value.scope, manifest.scope) || !same(value.identity, manifest.identity)) throw new CanonicalDataError("Lease history payload identity or scope mismatch.");
    }
  }
  return value;
}

const recordSchema = z.object({ record_id: text, kind: z.enum(["holding", "transaction"]), instrument_id: text, venue: text, currency: text, quantity_unit: text, quantity: decimal, observed_at: time, cash_amount: decimal.nullable() });
const factSchema = recordSchema.extend({ source_id: text, origin: z.enum(["manual", "statement_csv"]), input_sha256: hash, published_at: time.nullable(), retrieved_at: time }).refine(row => row.kind !== "holding" || !row.quantity.startsWith("-") || !/[1-9]/.test(row.quantity.split("E")[0]));
const evidenceSchema = z.object({ scope: scopeSchema, records: z.array(factSchema), status: z.enum(["partial", "unavailable"]), complete: z.literal(false), execution_authority: z.literal(false), holdings_inferred_from_transactions: z.literal(false) }).refine(value => (value.records.length > 0) === (value.status === "partial")).refine(value => new Set(value.records.map(row => JSON.stringify([row.source_id, row.record_id, row.kind, row.observed_at]))).size === value.records.length);
export type PortfolioEvidence = z.infer<typeof evidenceSchema>;
export type EvidenceRecord = z.infer<typeof recordSchema>;
const receiptSchema = z.object({ batch_id: hash, input_sha256: hash, count: integer, verification: z.literal("user_declared"), complete: z.literal(false), execution_authority: z.literal(false) });
export type EvidenceReceipt = z.infer<typeof receiptSchema>;
export type EvidenceInput = { origin: "manual"; source_id: string; records: EvidenceRecord[] } | { origin: "statement_csv"; source_id: string; csv: string };

/** Strict CSV intake: no delimiter guessing, column dropping or partial-row import. */
function csvRecords(csv: string): EvidenceRecord[] {
  if (new TextEncoder().encode(csv).length > 2_000_000) throw new CanonicalDataError("CSV exceeds the 2,000,000-byte evidence limit.");
  const rows: string[][] = []; let row: string[] = []; let cell = ""; let quoted = false; let closed = false;
  const invalid = () => { throw new CanonicalDataError("Invalid CSV: use the canonical header and complete, correctly quoted rows."); };
  for (let i = 0; i < csv.length; i++) {
    const char = csv[i];
    if (quoted) {
      if (char === '"' && csv[i + 1] === '"') { cell += '"'; i++; }
      else if (char === '"') { quoted = false; closed = true; }
      else cell += char;
    } else if (char === "," || char === "\n" || char === "\r") {
      row.push(cell); cell = ""; closed = false;
      if (char !== ",") { rows.push(row); row = []; if (char === "\r" && csv[i + 1] === "\n") i++; }
    } else if (char === '"' && cell === "" && !closed) quoted = true;
    else { if (closed || char === '"') invalid(); cell += char; }
  }
  if (quoted) invalid();
  if (cell !== "" || row.length || closed) rows.push([...row, cell]);
  const header = rows.shift() ?? [];
  const required = ["record_id", "kind", "instrument_id", "venue", "currency", "quantity_unit", "quantity", "observed_at"];
  if (new Set(header).size !== header.length || required.some(field => !header.includes(field)) || header.some(field => ![...required, "cash_amount"].includes(field))) invalid();
  return rows.map(cells => {
    if (cells.length !== header.length) invalid();
    const value = Object.fromEntries(header.map((field, index) => [field, cells[index]]));
    return recordSchema.parse({ ...value, cash_amount: value.cash_amount || null });
  });
}

// Python's canonical_json uses ensure_ascii=True. Portfolio manifests contain
// strings, booleans, null and safe integers only (never floating-point money).
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => `${canonical(key)}:${canonical(item)}`).join(",")}}`;
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
}
async function sha256(value: string) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))), byte => byte.toString(16).padStart(2, "0")).join("");
}
function normaliseTime(value: string): string {
  time.parse(value);
  const fraction = value.match(/\.(\d+)/)?.[1]?.padEnd(6, "0") ?? "000000";
  const whole = new Date(value).toISOString().slice(0, 19);
  return `${whole}${fraction === "000000" ? "" : `.${fraction}`}+00:00`;
}
function normaliseDecimal(value: string): string {
  if (value.length > 128 || !/^-?\d+(?:\.\d+)?$/.test(value)) throw new CanonicalDataError("Use exact decimal strings without exponents, spaces or separators.");
  const negative = value.startsWith("-") ? "-" : "";
  const [whole, fraction = ""] = value.replace(/^-/, "").split(".");
  const digits = (whole + fraction).replace(/^0+/, "") || "0";
  const exponent = digits.length - fraction.length - 1;
  if (exponent < -6) return `${negative}${digits[0]}${digits.length > 1 ? `.${digits.slice(1)}` : ""}E${exponent}`;
  return `${negative}${whole.replace(/^0+(?=\d)/, "")}${fraction ? `.${fraction}` : ""}`;
}
function normaliseRecord(value: EvidenceRecord): EvidenceRecord {
  const row = recordSchema.strict().parse(value);
  const quantity = normaliseDecimal(row.quantity);
  if (row.kind === "holding" && row.quantity.startsWith("-") && /[1-9]/.test(row.quantity)) throw new CanonicalDataError("A declared holding cannot have a negative quantity.");
  return { ...row, quantity, observed_at: normaliseTime(row.observed_at), cash_amount: row.cash_amount === null ? null : normaliseDecimal(row.cash_amount) };
}
function same(a: unknown, b: unknown) { return canonical(a) === canonical(b); }

function subscribeScope(notify: () => void) {
  const unsubscribers = [useAuthStore.subscribe(notify), useBrokerStore.subscribe(notify), useModeStore.subscribe(notify), useConnectionStore.subscribe(notify)];
  return () => unsubscribers.forEach(unsubscribe => unsubscribe());
}
/** Synchronous retirement also catches A→B→A, before passive effects commit old evidence. */
export function useCanonicalScopeKey() {
  return useSyncExternalStore(subscribeScope, () => captureOperatorIncidentScope().generation);
}
export function canonicalDataAvailable() {
  return useAuthStore.getState().status === "logged-in" && !isDemoAuthSession();
}
const subscribeOnline = (notify: () => void) => onlineManager.subscribe(notify);
export function useCanonicalDataOnline() {
  return useSyncExternalStore(subscribeOnline, () => onlineManager.isOnline());
}
export class CanonicalDataError extends Error {
  constructor(message: string, readonly code = "invalid_data_response", readonly httpStatus = 0) { super(message); }
}
export function canonicalError(error: unknown): string {
  return error instanceof CanonicalDataError ? error.message : "Canonical data unavailable: invalid or incomplete response.";
}

/** Per-mounted-view transport fence; credentials are captured, never taken from a replacement session. */
export class CanonicalDataClient {
  private readonly fence = captureOperatorIncidentScope();
  private readonly headers = buildHeaders(false);
  private readonly base = getBase();
  private viewGeneration = 0;
  private readonly leases = new Set<string>();
  private readonly acquisitions = new Set<Promise<DatasetLease>>();
  private readonly releases = new Map<string, Promise<boolean>>();
  private readonly scopes = new Map<string, DataScope>();
  current() { return this.viewGeneration === 0 && onlineManager.isOnline() && canonicalDataAvailable() && isOperatorIncidentScopeCurrent(this.fence); }
  viewRevision() { return this.viewGeneration; }
  pendingLeaseIds() { return [...this.leases]; }
  dispose() {
    this.viewGeneration++;
    // No retry loop, credential substitution or fabricated release on failure.
    return Promise.allSettled([...this.acquisitions, ...[...this.leases].map(id => this.release(id))]);
  }
  private assertCurrent() {
    if (!this.current()) throw new CanonicalDataError("Canonical data belongs to a retired or unavailable session.", "retired_scope");
  }
  private async request(path: string, method = "GET", body?: unknown, options: { retirement?: boolean; captureReceipt?: boolean } = {}): Promise<unknown> {
    if (!options.retirement) this.assertCurrent();
    const revision = this.viewGeneration;
    const checkResponse = () => {
      if (!options.retirement && !options.captureReceipt) {
        this.assertCurrent();
        if (revision !== this.viewGeneration) throw new CanonicalDataError("Response belongs to a retired view.");
      }
    };
    let response: Response;
    try {
      response = await fetch(`${this.base}${path}`, { method, headers: { ...this.headers, ...(body === undefined ? {} : { "Content-Type": "application/json" }) }, cache: "no-store", credentials: "omit", ...(options.retirement ? { keepalive: true } : {}), ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    } catch { throw new CanonicalDataError("Canonical data unavailable: transport failed.", "transport_unavailable"); }
    checkResponse();
    const raw: unknown = await response.json();
    checkResponse();
    const envelope = z.object({ status: z.string(), data: z.unknown().optional(), code: z.string().optional() }).parse(raw);
    if (!response.ok || envelope.status !== "success") {
      const code = envelope.code && /^[a-z_]{1,96}$/.test(envelope.code) ? envelope.code : `http_${response.status}`;
      throw new CanonicalDataError(`Canonical data refused or unavailable: ${code}.`, code, response.status);
    }
    return envelope.data;
  }
  async history(snapshotId: string, scope: DataScope, dataset?: Dataset) {
    hash.parse(snapshotId);
    const manifest = validateHistory(await this.request(`/v1/historify/snapshots/${snapshotId}`));
    if (manifest.snapshot_id !== snapshotId || !same(manifest.scope, scope) || (dataset?.source_kind === "recorded_history" && !same(manifest.identity, dataset.identity))) throw new CanonicalDataError("Immutable history manifest identity or scope mismatch.");
    return manifest;
  }
  private pinScope(family: string, scope: DataScope) {
    const previous = this.scopes.get(family);
    if (previous && !same(scope, previous)) throw new CanonicalDataError("Canonical data scope mismatch; retire this session view before reading again.");
    this.scopes.set(family, scope);
  }
  async datasets() {
    const result = catalogueSchema.parse(await this.request("/api/v1/data/datasets"));
    this.pinScope("history", result.scope);
    return result;
  }
  acquire(dataset: Dataset, scope: DataScope): Promise<DatasetLease> {
    const pending = this.acquireOnce(dataset, scope);
    this.acquisitions.add(pending);
    void pending.then(() => this.acquisitions.delete(pending), () => this.acquisitions.delete(pending));
    return pending;
  }
  private async acquireOnce(dataset: Dataset, scope: DataScope): Promise<DatasetLease> {
    if (dataset.source_kind !== "recorded_history" || dataset.status === "unavailable") throw new CanonicalDataError("This acquisition is unavailable; no source fallback is permitted.");
    const generation = this.viewGeneration;
    const raw = await this.request("/api/v1/data/leases", "POST", { dataset_id: dataset.dataset_id }, { captureReceipt: true });
    // Keep the exact handle before decoding the observation or checking retirement.
    const { lease_id } = z.object({ lease_id: z.string().regex(/^[a-f0-9]{32}$/) }).parse(raw);
    this.leases.add(lease_id);
    try {
      this.assertCurrent();
      if (generation !== this.viewGeneration) throw new CanonicalDataError("Acquisition belongs to a retired view.");
      const receipt = z.object({ lease_id: z.string(), snapshot: leaseSnapshotSchema }).parse(raw);
      if (receipt.snapshot.dataset_id !== dataset.dataset_id || !same(receipt.snapshot.scope, scope) || !same(receipt.snapshot.identity, dataset.identity)) throw new CanonicalDataError("Dataset lease receipt mismatch.");
      const result = await this.readLease(receipt);
      this.assertCurrent();
      if (generation !== this.viewGeneration) throw new CanonicalDataError("Acquisition belongs to a retired view.");
      return result;
    } catch (error) {
      if (this.leases.has(lease_id)) {
        try { await this.release(lease_id); }
        catch { throw new CanonicalDataError(`Acquisition not confirmed; release outcome unknown for lease ${lease_id}.`); }
      }
      throw error;
    }
  }
  async readLease(lease: DatasetLease, afterSequence?: number): Promise<DatasetLease> {
    let raw: unknown;
    try { raw = await this.request(`/api/v1/data/leases/${lease.lease_id}${afterSequence === undefined ? "" : `?after_sequence=${afterSequence}`}`); }
    catch (error) {
      if (error instanceof CanonicalDataError && error.httpStatus === 404 && error.code === "dataset_or_lease_retired") {
        this.leases.delete(lease.lease_id);
        throw new CanonicalDataError("Exact lease is absent or retired; release is not confirmed. Reacquire explicitly.", "lease_retired", 404);
      }
      throw error;
    }
    const snapshot = validateSnapshot(raw);
    for (const key of ["dataset_id", "identity", "source", "scope", "policy_revision"] as const) {
      if (!same(snapshot[key], lease.snapshot[key])) throw new CanonicalDataError("Dataset lease readback mismatch.");
    }
    const previous = lease.snapshot.sequence;
    if (previous !== null && (snapshot.sequence === null || snapshot.sequence < previous)) throw new CanonicalDataError("Dataset sequence regressed.");
    if (previous === snapshot.sequence && ["payload", "observed_at", "published_at", "retrieved_at"].some(key => !same(snapshot[key as keyof LeaseSnapshot], lease.snapshot[key as keyof LeaseSnapshot]))) throw new CanonicalDataError("Dataset sequence conflict.");
    if (afterSequence !== undefined) {
      integer.parse(afterSequence);
      let last = afterSequence;
      for (const frame of snapshot.updates) {
        if (frame.sequence <= last || snapshot.sequence === null || frame.sequence > snapshot.sequence) throw new CanonicalDataError("Invalid dataset update sequence.");
        last = frame.sequence;
      }
      const gap = snapshot.updates.length > 0 && snapshot.updates[0].sequence > afterSequence + 1;
      if (snapshot.replay_gap !== gap || (snapshot.sequence !== null && last !== snapshot.sequence)) throw new CanonicalDataError("Dataset replay-gap or sequence mismatch.");
    }
    return { lease_id: lease.lease_id, snapshot };
  }
  release(leaseId: string): Promise<boolean> {
    if (!this.leases.has(leaseId)) return Promise.reject(new CanonicalDataError("No owned lease with this identity."));
    const pending = this.releases.get(leaseId);
    if (pending) return pending;
    const task = this.confirmRelease(leaseId).finally(() => this.releases.delete(leaseId));
    this.releases.set(leaseId, task);
    return task;
  }
  private async confirmRelease(leaseId: string) {
    const path = `/api/v1/data/leases/${leaseId}`;
    const result = z.object({ released: z.boolean() }).parse(await this.request(path, "DELETE", undefined, { retirement: true }));
    try { await this.request(path, "GET", undefined, { retirement: true }); }
    catch (error) {
      if (error instanceof CanonicalDataError && error.httpStatus === 404 && error.code === "dataset_or_lease_retired") { this.leases.delete(leaseId); return result.released; }
      throw error;
    }
    throw new CanonicalDataError("Release is not confirmed: exact lease is still readable.");
  }
  async readPortfolio(): Promise<PortfolioEvidence> {
    const result = evidenceSchema.parse(await this.request("/api/v1/data/portfolio/evidence"));
    this.pinScope("portfolio", result.scope);
    return result;
  }
  async appendPortfolio(input: EvidenceInput, scope: DataScope, onReceipt: (receipt: EvidenceReceipt) => void) {
    input = z.discriminatedUnion("origin", [
      z.object({ origin: z.literal("manual"), source_id: text, records: z.array(recordSchema.strict()).min(1).max(10_000) }).strict(),
      z.object({ origin: z.literal("statement_csv"), source_id: text, csv: z.string() }).strict(),
    ]).parse(input);
    const rawRecords = input.origin === "manual" ? input.records : csvRecords(input.csv);
    const records = z.array(recordSchema.strict()).min(1).max(10_000).parse(rawRecords).map(normaliseRecord);
    const unique = new Map<string, EvidenceRecord>();
    for (const row of records) {
      const key = canonical([row.record_id, row.kind, row.observed_at]);
      const previous = unique.get(key);
      if (previous && !same(row, previous)) throw new CanonicalDataError("Conflicting CSV or manual rows require explicit reconciliation; nothing submitted.");
      unique.set(key, row);
    }
    const input_sha256 = await sha256(input.origin === "manual" ? canonical(input.records) : input.csv);
    const manifest = { schema_version: 1, scope: scopeSchema.parse(scope), source_id: input.source_id, origin: input.origin, input_sha256, records, verification: "user_declared", complete: false, execution_authority: false };
    const expected = await sha256(canonical(manifest));
    const receipt = receiptSchema.parse(await this.request("/api/v1/data/portfolio/evidence", "POST", input));
    onReceipt(receipt);
    if (receipt.batch_id !== expected || receipt.input_sha256 !== input_sha256 || receipt.count !== records.length) throw new CanonicalDataError("Receipt mismatch. Submission outcome is not confirmed; do not resubmit blindly.");
    const evidence = await this.readPortfolio();
    if (!same(evidence.scope, scope) || !records.every(record => evidence.records.some(fact => fact.source_id === input.source_id && same(recordSchema.parse(fact), record)))) throw new CanonicalDataError("Readback mismatch. Submission outcome is not confirmed; do not resubmit blindly.");
    this.assertCurrent();
    return { receipt, evidence };
  }
}
