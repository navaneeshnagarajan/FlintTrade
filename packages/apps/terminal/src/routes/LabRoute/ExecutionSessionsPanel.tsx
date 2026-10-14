import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RunPolicyPanel } from "./RunPolicyPanel";
import { ProtectionPolicyPanel } from "./ProtectionPolicyPanel";
import { captureAuthSessionFence, isAuthSessionFenceCurrent, useAuthStore } from "@/stores/authStore";
import { isDemoAuthSession } from "@/services/ftApi.helpers";
import { controlExecutionSession, createPaperSession, listExecutionSessions, readExecutionSession,
  type ExecutionSessionRecord, type SessionOperation } from "@/services/executionSessions";

export function ExecutionSessionsPanel() {
  const authGeneration = useAuthStore(state => state.sessionGeneration);
  const status = useAuthStore(state => state.status);
  const principal = useAuthStore(state => state.username);
  const client = useQueryClient();
  const key = ["execution-sessions", authGeneration, status, principal];
  const [symbols, setSymbols] = useState("");
  const [exchange, setExchange] = useState("NSE");
  const [strategy, setStrategy] = useState("");
  const [pendingId, setPendingId] = useState("");
  const [error, setError] = useState("");
  const [closeTarget, setCloseTarget] = useState<ExecutionSessionRecord | null>(null);
  const [policyRun, setPolicyRun] = useState("");
  const [protectionRun, setProtectionRun] = useState("");
  const enabled = status === "logged-in" && !isDemoAuthSession();
  const query = useQuery({ queryKey: key, queryFn: () => listExecutionSessions(), enabled, retry: false, refetchInterval: 5000 });
  // Mutation belongs to the query client/backend, not visibility. No cleanup
  // effect sends Stop, cancellation or Close when Activity hides this panel.
  const command = useMutation({
    mutationFn: async (input: { target?: ExecutionSessionRecord; operation?: SessionOperation; read?: string }) => {
      const fence = captureAuthSessionFence();
      const id = input.target?.run_id ?? input.read ?? crypto.randomUUID();
      setPendingId(id); setError("");
      try {
        if (input.read) return await readExecutionSession(id, fence);
        if (input.target && input.operation) return await controlExecutionSession(input.target, input.operation, fence);
        const config = { symbols: symbols.split(",").map(value => value.trim()).filter(Boolean), exchange,
          ...(strategy ? { strategy } : {}) };
        const created = await createPaperSession(id, config, fence);
        return await controlExecutionSession(created, "start", fence);
      } catch (reason) {
        if (isAuthSessionFenceCurrent(fence)) setError(`${id}: ${reason instanceof Error ? reason.message : "Execution unavailable"}`);
        throw reason;
      } finally {
        if (isAuthSessionFenceCurrent(fence)) await client.invalidateQueries({ queryKey: key });
      }
    },
    retry: false,
  });
  return <section className="space-y-4 min-w-0" aria-label="Execution sessions">
    <header>
      <h3 className="text-lg font-semibold">Paper forward runs</h3>
      <p className="text-sm text-text-secondary">Independent run books. Terminal’s Live account and mode remain unchanged.</p>
      <p className="text-xs text-text-muted">Runs belong to the backend and continue across app switches and UI closure. Logout retires entries; restart requires reconciliation and explicit rearm. Native Live execution remains unavailable.</p>
    </header>
    <div className="grid gap-3 sm:grid-cols-2 rounded border border-border-default p-4">
      <div><Label htmlFor="paper-symbols">Symbols</Label><Input id="paper-symbols" value={symbols} onChange={event => setSymbols(event.target.value)} placeholder="Exact symbols, comma-separated" /></div>
      <div><Label htmlFor="paper-exchange">Exchange</Label><Input id="paper-exchange" value={exchange} onChange={event => setExchange(event.target.value)} /></div>
      <div className="sm:col-span-2"><Label htmlFor="paper-strategy">Registered strategy (optional)</Label><Input id="paper-strategy" value={strategy} onChange={event => setStrategy(event.target.value)} placeholder="Exact core-registered Paper strategy; blank uses Practice agent" /></div>
      <p className="text-xs text-text-muted sm:col-span-2">A strategy requires an explicit Paper execution contract in the core. Otherwise uses the existing Practice agent’s configured model and risk rules. Unavailable inputs block entries; no market data is invented. Every start creates a new run identity, even for the same strategy.</p>
      <Button disabled={!enabled || command.isPending || !symbols.trim()} onClick={() => command.mutate({})}>Start Paper run</Button>
      <Button variant="outline" disabled={!enabled || query.isFetching} onClick={() => void query.refetch()}>Refresh runs</Button>
    </div>
    {!enabled ? <p>Installed operator session required. Preview does not create runs.</p> : null}
    {command.isPending ? <p role="status">Pending exact run: {pendingId}. Do not resend.</p> : null}
    {error ? <div role="alert" className="text-sm text-warning break-words">{error}<Button variant="outline" disabled={command.isPending} onClick={() => command.mutate({ read: pendingId })}>Read exact run</Button></div> : null}
    {query.isError ? <p role="alert">Run census unavailable — this is not an empty or stopped book.</p> : null}
    {query.isLoading ? <p role="status">Reading run identities…</p> : null}
    {!query.isError && query.data?.length === 0 ? <p>No registered runs for this operator. Historical custody may still require reconciliation.</p> : null}
    {(query.data ?? []).map(row => <section key={row.run_id} aria-label={`${row.environment === "paper" ? "Paper" : "Live"} run ${row.run_id}`} className="rounded border border-border-default p-4 space-y-3 min-w-0">
      <div className="flex flex-wrap gap-2 items-center"><h4 className="font-mono break-all">{row.run_id}</h4><span>{row.state}</span></div>
      <p className="text-xs break-all">{row.account} · {row.environment} · generation {row.generation} · {row.entries_armed ? "Entries armed" : "Entries retired"}</p>
      <p className="text-xs">Protection: {row.protection}. Stop entries does not cancel working orders or close positions.</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={!enabled} onClick={() => setPolicyRun(policyRun === row.run_id ? "" : row.run_id)}>{policyRun === row.run_id ? "Hide run policy" : "Configure run policy"}</Button>
        <Button variant="outline" disabled={!enabled} onClick={() => setProtectionRun(protectionRun === row.run_id ? "" : row.run_id)}>{protectionRun === row.run_id ? "Hide protection policy" : "Protection policy"}</Button>
        <Button variant="outline" disabled={command.isPending || !row.entries_armed} onClick={() => command.mutate({ target: row, operation: "stop" })}>Stop entries</Button>
        <Button variant="outline" disabled={command.isPending || row.environment !== "paper"} onClick={() => setCloseTarget(row)}>Close run positions…</Button>
        {row.state === "ready" || row.state === "rearm_required" ? <Button disabled={command.isPending || row.environment !== "paper"} onClick={() => command.mutate({ target: row, operation: row.state === "ready" ? "start" : "rearm" })}>{row.state === "ready" ? "Start exact run" : "Rearm exact run"}</Button> : null}
      </div>
      {closeTarget?.run_id === row.run_id ? <div className="border border-warning p-3 space-y-2" role="group" aria-label="Confirm exact run Close">
        <p>Close only {closeTarget.run_id} on {closeTarget.account}, generation {closeTarget.generation}? No unrelated positions. A request is not proof of flatness.</p>
        <Button disabled={command.isPending} onClick={() => { command.mutate({ target: closeTarget, operation: "close" }); setCloseTarget(null); }}>Confirm Close</Button>
        <Button variant="outline" onClick={() => setCloseTarget(null)}>Keep positions</Button>
      </div> : null}
      {policyRun === row.run_id ? <RunPolicyPanel key={`${row.run_id}:${row.generation}`} scope={row} /> : null}
      {protectionRun === row.run_id ? <ProtectionPolicyPanel key={`${row.run_id}:${row.generation}`} scope={row} /> : null}
      {row.books === null ? <p>Ledger unavailable. Exposure and outstanding orders are unknown.</p> : <>
        <p className="text-sm">{row.books.positions.length} open position rows · {row.books.orders.length} order records · {row.books.trades.length} fill records</p>
        <details><summary>Run ledger and P&amp;L</summary><pre className="text-xs overflow-auto max-h-80 whitespace-pre-wrap break-words">{JSON.stringify(row.books, null, 2)}</pre></details>
      </>}
    </section>)}
  </section>;
}
