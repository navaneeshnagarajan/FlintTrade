import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { CanonicalDataClient, canonicalDataAvailable, canonicalError, useCanonicalScopeKey, type EvidenceRecord, type EvidenceReceipt } from "@/services/canonicalData";

export function CanonicalPortfolioEvidence() {
  const scopeKey = useCanonicalScopeKey();
  return <section aria-label="Canonical portfolio evidence" className="min-w-0 space-y-3 rounded border border-border-default p-3 text-sm">
    <h2 className="font-semibold">Canonical portfolio evidence</h2>
    <p>User-declared holdings and transactions — incomplete evidence, not a complete account book. No verified valuations or XIRR. Transactions do not imply holdings or trading authority.</p>
    {canonicalDataAvailable() ? <EvidenceView key={scopeKey} scopeKey={scopeKey} /> : <p>Installed operator session required. Evidence intake is unavailable in the public preview.</p>}
  </section>;
}
const emptyRecord = (): EvidenceRecord => ({ record_id: "", kind: "holding", instrument_id: "", venue: "", currency: "", quantity_unit: "", quantity: "", observed_at: "", cash_amount: null });
const fields = ["record_id", "instrument_id", "venue", "currency", "quantity_unit", "quantity", "observed_at", "cash_amount"] as const;
function EvidenceView({ scopeKey }: { scopeKey: number }) {
  const [client] = useState(() => new CanonicalDataClient());
  const cache = useQueryClient();
  const queryKey = ["canonical-data", "portfolio", scopeKey];
  const evidence = useQuery({ queryKey, queryFn: () => client.readPortfolio(), retry: false, gcTime: 0 });
  const [record, setRecord] = useState(emptyRecord);
  const [source, setSource] = useState("");
  const [origin, setOrigin] = useState<"manual" | "statement_csv">("manual");
  const [csv, setCsv] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState<EvidenceReceipt | null>(null);
  const [verified, setVerified] = useState(false);
  const mounted = useRef(false);
  const reader = useRef<FileReader | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; reader.current?.abort(); }; }, []);
  function chooseFile(file: File | undefined) {
    reader.current?.abort();
    if (!file) return;
    setCsv(""); setError("");
    if (file.size > 2_000_000) { setError("CSV exceeds the 2,000,000-byte evidence limit."); return; }
    const reading = new FileReader(); reader.current = reading;
    reading.onload = () => {
      if (!mounted.current || !client.current() || reader.current !== reading || !(reading.result instanceof ArrayBuffer)) return;
      try { setCsv(new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(reading.result)); }
      catch { setError("Statement must be valid UTF-8. Nothing submitted."); }
    };
    reading.onerror = () => { if (mounted.current && client.current() && reader.current === reading) setError("Statement file could not be read. Nothing submitted."); };
    reading.readAsArrayBuffer(file);
  }
  async function submit() {
    if (busy || !evidence.data || evidence.error) return;
    setBusy(true); setError(""); setReceipt(null); setVerified(false);
    try {
      const result = await client.appendPortfolio(origin === "manual" ? { origin, source_id: source, records: [record] } : { origin, source_id: source, csv }, evidence.data.scope, value => { if (mounted.current && client.current()) setReceipt(value); });
      if (!mounted.current || !client.current()) return;
      cache.setQueryData(queryKey, result.evidence);
      setVerified(true); setRecord(emptyRecord()); setSource(""); setCsv("");
    } catch (failure) { if (mounted.current && client.current()) setError(canonicalError(failure)); }
    finally { if (mounted.current && client.current()) setBusy(false); }
  }
  return <>
    <form onSubmit={event => { event.preventDefault(); void submit(); }} className="space-y-3">
      <p>Explicit manual record or canonical statement CSV. Raw input stays only in this view until cleared; it is not stored in browser caches or logs.</p>
      <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" disabled={busy} aria-pressed={origin === "manual"} onClick={() => setOrigin("manual")}>Manual record</Button><Button type="button" variant="outline" disabled={busy} aria-pressed={origin === "statement_csv"} onClick={() => setOrigin("statement_csv")}>Statement CSV</Button></div>
      <p>Explicit manual record. Required identity is never inferred. Quantity and cash use exact decimals; observed_at requires an ISO timestamp with timezone. Blank cash remains unavailable.</p>
      <fieldset disabled={busy} className="space-y-3">
        <label className="block">Evidence source ID<Input value={source} onChange={event => setSource(event.target.value)} autoComplete="off" /></label>
        {origin === "manual" ? <>
        <div className="flex flex-wrap gap-2">{(["holding", "transaction"] as const).map(kind => <Button key={kind} type="button" variant="outline" aria-pressed={record.kind === kind} onClick={() => setRecord(current => ({ ...current, kind }))}>{kind}</Button>)}</div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">{fields.map(field => <label key={field} className="block">{field}<Input value={record[field] ?? ""} onChange={event => setRecord(current => ({ ...current, [field]: field === "cash_amount" && event.target.value === "" ? null : event.target.value }))} autoComplete="off" /></label>)}</div>
        </> : <><p className="break-all text-xs">CSV header: record_id,kind,instrument_id,venue,currency,quantity_unit,quantity,observed_at,cash_amount. No PDF parsing or automatic instrument mapping. Up to 10,000 rows / 2,000,000 UTF-8 bytes.</p><label className="block">Choose statement CSV<Input type="file" accept=".csv,text/csv" onChange={event => { chooseFile(event.target.files?.[0]); event.target.value = ""; }} /></label><label className="block">Statement CSV content<Textarea autoComplete="off" value={csv} onChange={event => setCsv(event.target.value)} rows={5} /></label></>}
        <div className="flex flex-wrap gap-2"><Button type="submit" disabled={!evidence.data || !!evidence.error}>Submit declared evidence</Button><Button type="button" variant="outline" onClick={() => { reader.current?.abort(); setRecord(emptyRecord()); setCsv(""); setSource(""); }}>Clear input</Button></div>
      </fieldset>
    </form>
    {busy ? <p role="status">Submitting and checking exact readback…</p> : null}
    {error ? <p role="alert">{error} No confirmed import without matching receipt and readback.</p> : null}
    {receipt ? <p className="break-all" role="status">{verified ? "Receipt and declared-fact readback matched" : "Received receipt — not yet verified"}: {receipt.batch_id} · input SHA-256 {receipt.input_sha256} · {receipt.count} declared records. Still incomplete evidence.</p> : null}
    <Button variant="outline" size="sm" disabled={evidence.isFetching || busy} onClick={() => void evidence.refetch()}>Read portfolio evidence</Button>
    {evidence.isPending ? <p role="status">Reading evidence…</p> : null}
    {evidence.error ? <p role="alert">{canonicalError(evidence.error)}</p> : null}
    {evidence.data && !evidence.error ? <>
      <p className="break-all">Server scope: {JSON.stringify(evidence.data.scope)}</p>
      {evidence.data.status === "unavailable" ? <p>No declared evidence available. This does not establish an empty or flat account.</p> : <p>Partial, user-declared evidence only.</p>}
      <ul className="space-y-3 pb-2" aria-label="Declared portfolio records">
        {evidence.data.records.map(row => <li key={JSON.stringify([row.source_id, row.record_id, row.kind, row.observed_at])} className="[overflow-wrap:anywhere] border-t border-border-default pt-2">
          <p><strong>{row.instrument_id}</strong> · {row.kind} · {row.venue} · {row.currency}</p>
          <p>{row.quantity} {row.quantity_unit}</p><p>Cash amount: {row.cash_amount ?? "unavailable"}</p>
          <p>Source: {row.source_id} · {row.origin} · Record: {row.record_id}</p>
          <p>Observed: {row.observed_at} · Published: {row.published_at ?? "unavailable"} · Retrieved: {row.retrieved_at}</p>
          <p className="break-all font-mono text-xs">Input SHA-256: {row.input_sha256}</p>
        </li>)}
      </ul>
    </> : null}
  </>;
}
