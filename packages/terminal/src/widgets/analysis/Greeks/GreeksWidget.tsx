/**
 * GreeksWidget — Portfolio-level Options Greeks dashboard for FlintTrade terminal.
 *
 * Features:
 *   - Summary cards: Net Delta, Net Gamma, Net Theta, Net Vega
 *     Delta: positive = green, negative = red
 *     Theta: always red (time decay cost)
 *     Gamma/Vega: accent blue (neutral)
 *   - Per-position table: Symbol, Qty, LTP, Delta, Gamma, Theta, Vega, IV
 *   - Fetches positionbook then calls getOptionGreeks for each F&O position
 *   - Total row at bottom
 *   - Auto-refresh: 10s during market hours, 60s off-market
 *   - "No F&O positions" empty state
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import { RefreshCw, AlertCircle, TrendingDown, Activity } from "lucide-react";
import { getPositionbook, getOptionGreeks } from "../../../services/api";
import type { Position } from "../../../types/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FlexLayoutNode {
  getId?: () => string;
}

/** Raw position from OpenAlgo — may have additional fields beyond typed Position */
interface RawPosition extends Position {
  tradingsymbol?: string;
  net_quantity?: number;
  unrealised_pnl?: number;
  m2m?: number;
}

/** Raw Greeks object from getOptionGreeks — field names vary across brokers */
interface RawGreeks {
  delta?: number;
  Delta?: number;
  gamma?: number;
  Gamma?: number;
  theta?: number;
  Theta?: number;
  vega?: number;
  Vega?: number;
  iv?: number;
  implied_volatility?: number;
  IV?: number;
  vix?: number;
}

interface GreeksRow {
  symbol: string;
  qty: number;
  ltp: number | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  iv: number | null;
}

interface PortfolioTotals {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
}

type ColorScheme = "delta" | "theta" | "neutral";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isMarketHours(): boolean {
  const now = new Date();
  const ist = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  const mins = ist.getHours() * 60 + ist.getMinutes();
  return mins >= 555 && mins <= 930;
}

function isFnO(position: RawPosition): boolean {
  const exchange = (position.exchange || "").toUpperCase();
  const symbol   = (position.symbol   || "").toUpperCase();
  const fnOExchanges = ["NFO", "BFO", "MCX", "CDS"];
  if (fnOExchanges.includes(exchange)) return true;
  return /CE$|PE$/.test(symbol);
}

function parseOptionSymbol(
  symbol: string,
  exchange: string
): { symbol: string; exchange: string; optionType: string } | null {
  const s = (symbol || "").toUpperCase();
  const optionType = s.endsWith("CE") ? "CE" : s.endsWith("PE") ? "PE" : null;
  if (!optionType) return null;
  return { symbol: s, exchange: exchange || "NFO", optionType };
}

const NUM2 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
const NUM4 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 4 });
const NUM  = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

function fmt2(v: number | null | undefined): string {
  if (v == null || isNaN(Number(v))) return "—";
  const n = Number(v);
  return `${n >= 0 ? "+" : ""}${NUM2.format(n)}`;
}

function fmt4(v: number | null | undefined): string {
  if (v == null || isNaN(Number(v))) return "—";
  const n = Number(v);
  return `${n >= 0 ? "+" : ""}${NUM4.format(n)}`;
}

function fmtLtp(v: number | null | undefined): string {
  if (v == null || isNaN(Number(v))) return "—";
  return NUM.format(Number(v));
}

function fmtIV(v: number | null | undefined): string {
  if (v == null || isNaN(Number(v))) return "—";
  const n = Number(v);
  const pct = n > 2 ? n : n * 100;
  return `${pct.toFixed(1)}%`;
}

// ---------------------------------------------------------------------------
// Summary card component
// ---------------------------------------------------------------------------

interface GreekCardProps {
  label: string;
  value: number | null | undefined;
  colorScheme: ColorScheme;
  description?: string;
}

function GreekCard({ label, value, colorScheme, description }: GreekCardProps) {
  const numVal = value != null && !isNaN(Number(value)) ? Number(value) : null;

  let valueColor: string;
  if (colorScheme === "delta") {
    valueColor = numVal == null ? "text-text-muted" : numVal >= 0 ? "text-profit" : "text-loss";
  } else if (colorScheme === "theta") {
    valueColor = "text-loss";
  } else {
    valueColor = "text-accent";
  }

  const displayValue = numVal != null ? `${numVal >= 0 ? "+" : ""}${NUM2.format(numVal)}` : "—";

  return (
    <div className="flex-1 min-w-0 bg-surface-card border border-border-default rounded px-3 py-2">
      <div className="text-xxs text-text-muted uppercase tracking-wider mb-1">{label}</div>
      <div className={`font-mono tabular-nums text-base font-semibold leading-tight ${valueColor}`}>
        {displayValue}
      </div>
      {description && (
        <div className="text-xs text-text-muted mt-0.5 truncate">{description}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

interface GreeksWidgetProps {
  node?: FlexLayoutNode;
}

export default function GreeksWidget({ node: _node }: GreeksWidgetProps) {
  const [positions,  setPositions]  = useState<RawPosition[]>([]);
  const [greeksMap,  setGreeksMap]  = useState<Record<string, RawGreeks>>({});
  const [ltpMap,     setLtpMap]     = useState<Record<string, number>>({});
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fnoPositions = useMemo(
    () => positions.filter((p) => isFnO(p as RawPosition)),
    [positions]
  );

  // Fetch all data
  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      let rawPositions: RawPosition[] = [];
      try {
        const pb = await getPositionbook();
        rawPositions = Array.isArray(pb) ? (pb as RawPosition[]) : [];
      } catch (e) {
        setError(`Positionbook error: ${(e as Error).message}`);
        return;
      }

      setPositions(rawPositions);

      const ltpSnapshot: Record<string, number> = {};
      rawPositions.forEach((p) => {
        if (p.ltp != null) ltpSnapshot[p.symbol] = Number(p.ltp);
      });
      setLtpMap((prev) => ({ ...prev, ...ltpSnapshot }));

      const fno = rawPositions.filter((p) => isFnO(p));

      if (fno.length === 0) {
        setGreeksMap({});
        setLastRefresh(new Date());
        return;
      }

      const greekResults = await Promise.allSettled(
        fno.map(async (pos) => {
          const parsed = parseOptionSymbol(pos.symbol, pos.exchange);
          if (!parsed) return null;

          try {
            const data = await getOptionGreeks(parsed.symbol, parsed.exchange);
            return { symbol: pos.symbol, data };
          } catch {
            return null;
          }
        })
      );

      const newGreeksMap: Record<string, RawGreeks> = {};
      greekResults.forEach((result) => {
        if (result.status === "fulfilled" && result.value) {
          const { symbol, data } = result.value;
          const raw = data as unknown as RawGreeks | RawGreeks[];
          const greekObj: RawGreeks | null = Array.isArray(raw) ? (raw[0] ?? null) : raw;
          if (greekObj) newGreeksMap[symbol] = greekObj;
        }
      });

      setGreeksMap(newGreeksMap);
      setLastRefresh(new Date());
    } finally {
      setLoading(false);
    }
  }, []);

  // Auto-refresh
  useEffect(() => {
    fetchAll();
    const interval = isMarketHours() ? 10_000 : 60_000;
    const id = setInterval(fetchAll, interval);
    return () => clearInterval(id);
  }, [fetchAll]);

  // Compute portfolio totals
  const { rows, totals } = useMemo((): { rows: GreeksRow[]; totals: PortfolioTotals } => {
    const computedRows: GreeksRow[] = fnoPositions.map((pos) => {
      const qty = parseInt(String(pos.quantity ?? (pos as RawPosition).net_quantity ?? 0), 10);
      const ltp = ltpMap[pos.symbol] ?? (parseFloat(String(pos.ltp || 0)) || null);
      const g: RawGreeks = greeksMap[pos.symbol] ?? {};

      const rawDelta = g.delta ?? g.Delta ?? null;
      const rawGamma = g.gamma ?? g.Gamma ?? null;
      const rawTheta = g.theta ?? g.Theta ?? null;
      const rawVega  = g.vega  ?? g.Vega  ?? null;
      const rawIV    = g.iv    ?? g.implied_volatility ?? g.IV ?? g.vix ?? null;

      const delta = rawDelta != null ? Number(rawDelta) * qty : null;
      const gamma = rawGamma != null ? Number(rawGamma) * qty : null;
      const theta = rawTheta != null ? Number(rawTheta) * qty : null;
      const vega  = rawVega  != null ? Number(rawVega)  * qty : null;

      return {
        symbol: pos.symbol,
        qty,
        ltp,
        delta,
        gamma,
        theta,
        vega,
        iv: rawIV != null ? Number(rawIV) : null,
      };
    });

    function sum(key: keyof GreeksRow): number {
      return computedRows.reduce((acc, r) => {
        const v = r[key] as number | null;
        return v != null ? acc + v : acc;
      }, 0);
    }

    const totals: PortfolioTotals = {
      delta: sum("delta"),
      gamma: sum("gamma"),
      theta: sum("theta"),
      vega:  sum("vega"),
    };

    return { rows: computedRows, totals };
  }, [fnoPositions, greeksMap, ltpMap]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden select-none text-xs">

      {/* Header */}
      <div className="flex-none flex items-center justify-between px-3 py-1.5 bg-surface-card border-b border-border-default">
        <div className="flex items-center gap-1.5">
          <Activity size={12} className="text-accent" />
          <span className="font-heading font-semibold text-sm text-text-primary uppercase tracking-wider">
            Portfolio Greeks
          </span>
          {fnoPositions.length > 0 && (
            <span className="text-xs text-text-muted">
              · {fnoPositions.length} F&amp;O position{fnoPositions.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {lastRefresh && (
            <span className="text-xs text-text-muted font-mono">
              {lastRefresh.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
            </span>
          )}
          <button
            onClick={fetchAll}
            disabled={loading}
            className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
            title="Refresh"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex-none flex items-center gap-2 px-3 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} />
          <span>{error}</span>
        </div>
      )}

      {/* Summary cards */}
      <div className="flex-none flex gap-2 px-3 py-2 border-b border-border-default">
        <GreekCard
          label="Net Delta"
          value={fnoPositions.length > 0 ? totals.delta : null}
          colorScheme="delta"
          description="directional exposure"
        />
        <GreekCard
          label="Net Gamma"
          value={fnoPositions.length > 0 ? totals.gamma : null}
          colorScheme="neutral"
          description="delta sensitivity"
        />
        <GreekCard
          label="Net Theta"
          value={fnoPositions.length > 0 ? totals.theta : null}
          colorScheme="theta"
          description="daily time decay"
        />
        <GreekCard
          label="Net Vega"
          value={fnoPositions.length > 0 ? totals.vega : null}
          colorScheme="neutral"
          description="IV sensitivity"
        />
      </div>

      {/* Position table */}
      <div className="flex-1 overflow-auto">
        {loading && fnoPositions.length === 0 ? (
          <div className="h-full flex items-center justify-center text-text-muted gap-2">
            <RefreshCw size={13} className="animate-spin" />
            <span>Loading positions…</span>
          </div>
        ) : fnoPositions.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center gap-2 text-text-muted">
            <TrendingDown size={28} className="opacity-30" />
            <span className="text-sm">No F&amp;O positions</span>
            <span className="text-xs">Open options or futures positions to see portfolio Greeks</span>
          </div>
        ) : (
          <table className="w-full border-separate border-spacing-0">
            <thead className="sticky top-0 z-10 bg-surface-card">
              <tr>
                <th className="px-2 py-1 text-left text-xxs text-text-muted uppercase tracking-wider border-b border-border-default">Symbol</th>
                <th className="px-2 py-1 text-right text-xxs text-text-muted uppercase tracking-wider border-b border-border-default">Qty</th>
                <th className="px-2 py-1 text-right text-xxs text-text-muted uppercase tracking-wider border-b border-border-default">LTP</th>
                <th className="px-2 py-1 text-right text-xxs text-text-muted uppercase tracking-wider border-b border-border-default">Delta</th>
                <th className="px-2 py-1 text-right text-xxs text-text-muted uppercase tracking-wider border-b border-border-default">Gamma</th>
                <th className="px-2 py-1 text-right text-xxs text-loss/80 uppercase tracking-wider border-b border-border-default">Theta</th>
                <th className="px-2 py-1 text-right text-xxs text-text-muted uppercase tracking-wider border-b border-border-default">Vega</th>
                <th className="px-2 py-1 text-right text-xxs text-text-muted uppercase tracking-wider border-b border-border-default">IV</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const qtyColor = row.qty > 0 ? "text-profit" : row.qty < 0 ? "text-loss" : "text-text-muted";
                const deltaColor =
                  row.delta == null ? "text-text-muted"
                  : row.delta >= 0  ? "text-profit"
                  : "text-loss";

                return (
                  <tr key={row.symbol} className="border-b border-border-subtle hover:bg-surface-hover/40 transition-colors">
                    <td className="px-2 py-1 font-mono font-medium text-text-primary truncate max-w-35" title={row.symbol}>
                      {row.symbol}
                    </td>
                    <td className={`px-2 py-1 text-right font-mono tabular-nums ${qtyColor}`}>
                      {row.qty > 0 ? `+${row.qty}` : row.qty}
                    </td>
                    <td className="px-2 py-1 text-right font-mono tabular-nums text-text-secondary">
                      {fmtLtp(row.ltp)}
                    </td>
                    <td className={`px-2 py-1 text-right font-mono tabular-nums ${deltaColor}`}>
                      {fmt4(row.delta)}
                    </td>
                    <td className="px-2 py-1 text-right font-mono tabular-nums text-accent">
                      {fmt4(row.gamma)}
                    </td>
                    <td className="px-2 py-1 text-right font-mono tabular-nums text-loss">
                      {fmt4(row.theta)}
                    </td>
                    <td className="px-2 py-1 text-right font-mono tabular-nums text-accent">
                      {fmt4(row.vega)}
                    </td>
                    <td className="px-2 py-1 text-right font-mono tabular-nums text-text-secondary">
                      {fmtIV(row.iv)}
                    </td>
                  </tr>
                );
              })}
            </tbody>

            {rows.length > 1 && (
              <tfoot>
                <tr className="bg-surface-card border-t-2 border-border-default">
                  <td colSpan={3} className="px-2 py-1 text-xs text-text-muted uppercase tracking-wider font-semibold">
                    Total ({rows.length} legs)
                  </td>
                  <td className={`px-2 py-1 text-right font-mono tabular-nums font-semibold text-xs ${
                    totals.delta >= 0 ? "text-profit" : "text-loss"
                  }`}>
                    {fmt2(totals.delta)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono tabular-nums font-semibold text-xs text-accent">
                    {fmt2(totals.gamma)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono tabular-nums font-semibold text-xs text-loss">
                    {fmt2(totals.theta)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono tabular-nums font-semibold text-xs text-accent">
                    {fmt2(totals.vega)}
                  </td>
                  <td className="px-2 py-1 text-right text-text-muted">—</td>
                </tr>
              </tfoot>
            )}
          </table>
        )}
      </div>

      {/* Footer */}
      <div className="flex-none flex items-center justify-between px-3 py-1 bg-surface-card border-t border-border-default">
        <span className="text-xs text-text-muted">
          {isMarketHours() ? "Live · 10s refresh" : "Market closed · 60s refresh"}
        </span>
        <span className="text-xs text-text-muted">
          Greeks = per-leg × qty
        </span>
      </div>
    </div>
  );
}
