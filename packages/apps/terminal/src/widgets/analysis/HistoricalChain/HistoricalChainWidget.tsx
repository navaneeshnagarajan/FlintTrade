/**
 * HistoricalChainWidget — browse archived (expired) option chains.
 *
 * The ExpiryTracker archives each option chain as its expiry rolls off, so a
 * trader can review the OI / volume / LTP / IV structure of a past expiry. This
 * widget reads that archive via the historical endpoints:
 *   - getHistoricalExpiries(symbol) → the expiries captured for a symbol
 *   - getHistoricalChain(symbol, expiry) → the stored chain rows
 *
 * DATA HONESTY: this reads a real archive — there is no sample/demo data. When
 * nothing has been captured yet, the widget says so plainly rather than
 * fabricating a chain. (The archive fills as live expiries roll off, or after a
 * historical backfill.)
 */

import { useState, useMemo, memo } from "react";
import { Archive, ChevronDown } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { getHistoricalExpiries, getHistoricalChain } from "@/services/ftApi.data";
import type { HistoricalOptionRow } from "@/services/ftApi.data";

// ---------------------------------------------------------------------------
// Symbols (F&O underlyings whose chains are archived)
// ---------------------------------------------------------------------------

interface SymDef {
  label: string;
  exchange: string;
}

const SYMBOLS: SymDef[] = [
  { label: "NIFTY", exchange: "NFO" },
  { label: "BANKNIFTY", exchange: "NFO" },
  { label: "FINNIFTY", exchange: "NFO" },
  { label: "MIDCPNIFTY", exchange: "NFO" },
  { label: "SENSEX", exchange: "BFO" },
];

// ---------------------------------------------------------------------------
// Grouping: flat CE/PE rows → one row per strike
// ---------------------------------------------------------------------------

interface StrikeRow {
  strike: number;
  ce: HistoricalOptionRow | null;
  pe: HistoricalOptionRow | null;
}

function groupByStrike(rows: HistoricalOptionRow[]): StrikeRow[] {
  const byStrike = new Map<number, StrikeRow>();
  for (const row of rows) {
    let entry = byStrike.get(row.strike);
    if (!entry) {
      entry = { strike: row.strike, ce: null, pe: null };
      byStrike.set(row.strike, entry);
    }
    if (row.option_type === "CE") entry.ce = row;
    else if (row.option_type === "PE") entry.pe = row;
  }
  return [...byStrike.values()].sort((a, b) => a.strike - b.strike);
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

function fmtNum(v: number | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 1_00_000) return `${(v / 1_00_000).toFixed(1)}L`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
  return String(Math.round(v));
}

function fmtPrice(v: number | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(2);
}

function fmtIv(v: number | undefined): string {
  if (v == null || !Number.isFinite(v) || v <= 0) return "—";
  // IVs are stored in percent (e.g. 14.8).
  return `${(v > 1.5 ? v : v * 100).toFixed(1)}%`;
}

/**
 * True when the payload carries the backend's `is_sample_data: true` honesty
 * flag (propagated onto object payloads by the ftApi response unwrapper).
 */
function carriesSampleFlag(payload: unknown): boolean {
  return (
    typeof payload === "object" &&
    payload !== null &&
    (payload as { is_sample_data?: unknown }).is_sample_data === true
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function HistoricalChainWidget() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [showSymbolMenu, setShowSymbolMenu] = useState(false);
  const [expiry, setExpiry] = useState("");

  const symDef = useMemo(
    () => SYMBOLS.find((s) => s.label === symbol) ?? { label: symbol, exchange: "NFO" },
    [symbol],
  );

  const { data: expData, isLoading: loadingExpiries } = useQuery({
    queryKey: ["historical-expiries", symbol, symDef.exchange],
    queryFn: () => getHistoricalExpiries(symDef.label, symDef.exchange),
    staleTime: 5 * 60_000,
    retry: false,
  });

  const expiries = expData?.expiries ?? [];
  // The chosen expiry, falling back to the newest archived one.
  const selectedExpiry = expiry && expiries.includes(expiry) ? expiry : expiries[0] ?? "";

  const { data: chainData, isLoading: loadingChain } = useQuery({
    queryKey: ["historical-chain", symbol, symDef.exchange, selectedExpiry],
    queryFn: () => getHistoricalChain(symDef.label, selectedExpiry, symDef.exchange),
    enabled: Boolean(selectedExpiry),
    staleTime: 5 * 60_000,
    retry: false,
  });

  const strikes = useMemo(() => groupByStrike(chainData?.chain ?? []), [chainData]);
  const capturedAt = chainData?.chain?.[0]?.captured_at ?? null;

  // Badge keys off the payload FLAG: the archive endpoints serve real captures
  // (no local sample fallback exists here), but if the backend ever flags a
  // payload is_sample_data the fabrication must be visible.
  const isSample = carriesSampleFlag(expData) || carriesSampleFlag(chainData);

  const handleSymbol = (s: string) => {
    setSymbol(s);
    setExpiry("");
    setShowSymbolMenu(false);
  };

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Historical Option Chain widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Archive size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Historical Chain</span>
        {isSample && (
          <span
            className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            aria-label="Showing demo data, not a real archived chain"
            title="Demo data — the backend flagged this payload as fabricated sample values."
          >
            Demo data
          </span>
        )}
        <div className="flex-1" />

        {/* Symbol selector */}
        <div className="relative">
          <button
            onClick={() => setShowSymbolMenu((v) => !v)}
            aria-label={`Selected symbol: ${symbol}`}
            aria-expanded={showSymbolMenu}
            className="flex items-center gap-1 px-2 py-0.5 text-xs text-text-primary bg-surface-hover rounded border border-border-default hover:border-accent transition-colors"
          >
            {symbol}
            <ChevronDown size={10} aria-hidden="true" />
          </button>
          {showSymbolMenu && (
            <div
              className="absolute right-0 top-full mt-1 z-30 bg-surface-card border border-border-default rounded shadow-lg min-w-28"
              role="listbox"
              aria-label="Symbol selection"
            >
              {SYMBOLS.map((s) => (
                <button
                  key={s.label}
                  role="option"
                  aria-selected={s.label === symbol}
                  onClick={() => handleSymbol(s.label)}
                  className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover transition-colors ${s.label === symbol ? "text-accent" : "text-text-primary"}`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Expiry selector */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 border-b border-border-default bg-surface-base">
        <label htmlFor="hist-expiry" className="text-xxs text-text-muted uppercase tracking-wide">Expiry</label>
        <select
          id="hist-expiry"
          value={selectedExpiry}
          onChange={(e) => setExpiry(e.target.value)}
          disabled={expiries.length === 0}
          aria-label="Select archived expiry"
          className="flex-1 h-7 text-xs font-mono bg-surface-hover border border-border-default rounded px-2 text-text-primary disabled:opacity-50"
        >
          {expiries.length === 0 ? (
            <option value="">No archived expiries</option>
          ) : (
            expiries.map((e) => (
              <option key={e} value={e}>{e}</option>
            ))
          )}
        </select>
        {capturedAt && (
          <span className="text-xxs text-text-muted whitespace-nowrap" title={`Archived at ${capturedAt}`}>
            captured {capturedAt.slice(0, 10)}
          </span>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-auto">
        {loadingExpiries || loadingChain ? (
          <div className="flex items-center justify-center h-full text-xs text-text-muted">Loading…</div>
        ) : expiries.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-1 text-center px-4">
            <Archive size={22} className="text-text-disabled" aria-hidden="true" />
            <span className="text-xs text-text-muted">No historical chains captured for {symbol} yet.</span>
            <span className="text-xxs text-text-disabled">Chains are archived as live expiries roll off, or after a historical backfill.</span>
          </div>
        ) : strikes.length === 0 ? (
          <div className="flex items-center justify-center h-full text-xs text-text-muted">
            No strikes stored for this expiry.
          </div>
        ) : (
          <table className="w-full text-xxs" aria-label="Historical option chain table">
            <thead className="sticky top-0 bg-surface-card z-10">
              <tr className="border-b border-border-default text-text-muted">
                <th className="px-1 py-1 text-right font-medium" colSpan={4}>CALLS</th>
                <th className="px-2 py-1 text-center font-medium">Strike</th>
                <th className="px-1 py-1 text-left font-medium" colSpan={4}>PUTS</th>
              </tr>
              <tr className="border-b border-border-default text-text-muted">
                <th className="px-1 py-0.5 text-right font-normal">OI</th>
                <th className="px-1 py-0.5 text-right font-normal">Vol</th>
                <th className="px-1 py-0.5 text-right font-normal">LTP</th>
                <th className="px-1 py-0.5 text-right font-normal">IV</th>
                <th className="px-2 py-0.5 text-center font-normal" />
                <th className="px-1 py-0.5 text-left font-normal">IV</th>
                <th className="px-1 py-0.5 text-left font-normal">LTP</th>
                <th className="px-1 py-0.5 text-left font-normal">Vol</th>
                <th className="px-1 py-0.5 text-left font-normal">OI</th>
              </tr>
            </thead>
            <tbody>
              {strikes.map((row) => (
                <tr key={row.strike} className="border-b border-border-default/50 hover:bg-surface-hover transition-colors font-mono tabular-nums">
                  <td className="px-1 py-1 text-right text-text-secondary">{fmtNum(row.ce?.oi)}</td>
                  <td className="px-1 py-1 text-right text-text-muted">{fmtNum(row.ce?.volume)}</td>
                  <td className="px-1 py-1 text-right text-text-primary">{fmtPrice(row.ce?.ltp)}</td>
                  <td className="px-1 py-1 text-right text-text-muted">{fmtIv(row.ce?.iv)}</td>
                  <td className="px-2 py-1 text-center font-semibold text-text-primary bg-surface-card/60">{row.strike}</td>
                  <td className="px-1 py-1 text-left text-text-muted">{fmtIv(row.pe?.iv)}</td>
                  <td className="px-1 py-1 text-left text-text-primary">{fmtPrice(row.pe?.ltp)}</td>
                  <td className="px-1 py-1 text-left text-text-muted">{fmtNum(row.pe?.volume)}</td>
                  <td className="px-1 py-1 text-left text-text-secondary">{fmtNum(row.pe?.oi)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default memo(HistoricalChainWidget);
