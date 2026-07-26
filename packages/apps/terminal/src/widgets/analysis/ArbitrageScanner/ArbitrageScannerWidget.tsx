/**
 * ArbitrageScannerWidget — cash-future & cross-exchange arbitrage scanner (DP3).
 *
 * Two ranked tables:
 *   - Cash-future basis dislocations: observed basis (future − spot) vs the
 *     fair cost-of-carry, with the annualised carry yield and a cash-and-carry
 *     / reverse / fair signal.
 *   - Cross-exchange price gaps: same scrip on NSE vs BSE, with the buy/sell leg.
 *
 * Read-only analytics — no order placement. The scan universe and edge
 * threshold are operator-editable; live quotes for the universe are observed
 * client-side and posted to the backend scanner. Disconnected mode renders a
 * clearly-badged local sample behind the preview teaser; a connected response
 * flagged `is_sample_data` keeps the badge visible.
 */

import { memo, useEffect, useMemo, useState } from "react";
import { RefreshCw, Loader2, ArrowLeftRight, TrendingUp, TrendingDown, Minus, AlertCircle, SearchX } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useArbitrageScanner } from "./useArbitrageScanner";
import { SAMPLE_ARBITRAGE_SCAN } from "./sampleData";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { APP_VERSION_TAG } from "@/lib/appVersion";
import type { ArbSignal, ArbitrageScanResponse, CashFutureOpportunity, CrossExchangeOpportunity } from "@/types/api";

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

/** Default scan universe: index futures plus liquid NSE/BSE cross-listings. */
const DEFAULT_UNIVERSE_INPUT = "NIFTY, BANKNIFTY, RELIANCE, HDFCBANK, INFY, TATASTEEL";
const DEFAULT_EDGE_THRESHOLD = "1.0";

/** Debounce a changing value so typing does not refetch per keystroke. */
function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

function signalStyle(signal: ArbSignal): { cls: string; Icon: typeof TrendingUp; label: string } {
  if (signal === "cash_and_carry") return { cls: "text-green-500", Icon: TrendingUp, label: "Cash & carry" };
  if (signal === "reverse") return { cls: "text-red-500", Icon: TrendingDown, label: "Reverse" };
  return { cls: "text-text-muted", Icon: Minus, label: "Fair" };
}

function CashFutureRow({ opp }: { opp: CashFutureOpportunity }) {
  const { cls, Icon, label } = signalStyle(opp.signal);
  return (
    <tr className="border-b border-border-default/50 last:border-0">
      <td className="py-1.5 pr-2 text-text-primary font-medium">{opp.underlying}</td>
      <td className="py-1.5 px-2 text-right font-mono tabular-nums text-text-muted">{INR.format(opp.spot)}</td>
      <td className="py-1.5 px-2 text-right font-mono tabular-nums text-text-muted">{INR.format(opp.future_price)}</td>
      <td className={`py-1.5 px-2 text-right font-mono tabular-nums ${opp.basis >= 0 ? "text-green-500" : "text-red-500"}`}>
        {opp.basis >= 0 ? "+" : ""}{INR.format(opp.basis)}
      </td>
      <td className="py-1.5 px-2 text-right font-mono tabular-nums text-text-primary">{opp.annualised_return_pct.toFixed(1)}%</td>
      <td className={`py-1.5 pl-2 ${cls}`}>
        <span className="flex items-center gap-1"><Icon size={12} />{label}</span>
      </td>
    </tr>
  );
}

function CrossExchangeRow({ opp }: { opp: CrossExchangeOpportunity }) {
  return (
    <tr className="border-b border-border-default/50 last:border-0">
      <td className="py-1.5 pr-2 text-text-primary font-medium">{opp.symbol}</td>
      <td className="py-1.5 px-2 text-right font-mono tabular-nums text-text-muted">{opp.exchange_a} {INR.format(opp.price_a)}</td>
      <td className="py-1.5 px-2 text-right font-mono tabular-nums text-text-muted">{opp.exchange_b} {INR.format(opp.price_b)}</td>
      <td className="py-1.5 px-2 text-right font-mono tabular-nums text-text-primary">{opp.spread_pct.toFixed(3)}%</td>
      <td className="py-1.5 pl-2 text-text-primary">
        <span className="text-green-500">Buy {opp.buy_on}</span> · <span className="text-red-500">Sell {opp.sell_on}</span>
      </td>
    </tr>
  );
}

function ScanTables({ response }: { response: ArbitrageScanResponse }) {
  const scan = response.scan;
  return (
    <div className="flex-1 overflow-auto space-y-4">
      <div>
        <div className="text-[10px] uppercase tracking-wide text-text-muted mb-1">Cash-future basis</div>
        {scan.cash_future.length === 0 ? (
          <div className="py-1.5 text-text-muted">No cash-future dislocations found.</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-text-muted border-b border-border-default">
                <th className="py-1 pr-2 text-left font-medium">Scrip</th>
                <th className="py-1 px-2 text-right font-medium">Spot</th>
                <th className="py-1 px-2 text-right font-medium">Future</th>
                <th className="py-1 px-2 text-right font-medium">Basis</th>
                <th className="py-1 px-2 text-right font-medium">Ann. %</th>
                <th className="py-1 pl-2 text-left font-medium">Signal</th>
              </tr>
            </thead>
            <tbody>
              {scan.cash_future.map((opp) => (
                <CashFutureRow key={`${opp.exchange}:${opp.underlying}`} opp={opp} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-wide text-text-muted mb-1">Cross-exchange gaps</div>
        {scan.cross_exchange.length === 0 ? (
          <div className="py-1.5 text-text-muted">No cross-exchange gaps found.</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-text-muted border-b border-border-default">
                <th className="py-1 pr-2 text-left font-medium">Scrip</th>
                <th className="py-1 px-2 text-right font-medium">Venue A</th>
                <th className="py-1 px-2 text-right font-medium">Venue B</th>
                <th className="py-1 px-2 text-right font-medium">Gap %</th>
                <th className="py-1 pl-2 text-left font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {scan.cross_exchange.map((opp) => (
                <CrossExchangeRow key={opp.symbol} opp={opp} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function ArbitrageScannerWidget() {
  const isConnected = useBrokerConnected();

  const [universeInput, setUniverseInput] = useState(DEFAULT_UNIVERSE_INPUT);
  const [thresholdInput, setThresholdInput] = useState(DEFAULT_EDGE_THRESHOLD);
  const debouncedUniverse = useDebounced(universeInput, 600);
  const debouncedThreshold = useDebounced(thresholdInput, 600);

  const universe = useMemo(
    () => debouncedUniverse.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean),
    [debouncedUniverse],
  );
  const edgeThresholdPct = useMemo(() => {
    const v = Number.parseFloat(debouncedThreshold);
    return Number.isFinite(v) && v >= 0 ? v : 1.0;
  }, [debouncedThreshold]);

  const { data: live, isLoading, isFetching, isError, error, refetch } = useArbitrageScanner(
    { universe, edgeThresholdPct },
    isConnected,
  );

  // Disconnected mode renders the local sample (clearly badged, behind the
  // teaser). Connected mode renders ONLY the backend response — never the
  // local sample — so an error stays an error instead of fake tables.
  const response: ArbitrageScanResponse | undefined = isConnected
    ? live
    : { is_sample_data: true, scan: SAMPLE_ARBITRAGE_SCAN };
  // Fail closed: a present payload must say `is_sample_data: false` to be
  // labelled live. A missing flag reads as sample, not as real.
  const isSample = response != null && response.is_sample_data !== false;
  const isRealEmptyScan =
    response !== undefined &&
    !response.is_sample_data &&
    response.scan.cash_future.length === 0 &&
    response.scan.cross_exchange.length === 0;

  const content = (
    <div className="flex flex-col h-full gap-3 p-3 text-xs">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-1.5">
            <ArrowLeftRight size={14} /> Arbitrage Scanner
          </h3>
          <p className="text-[10px] text-text-muted">
            Cash-future basis &amp; cross-exchange
            {response !== undefined && ` · funding ${(response.scan.risk_free_rate * 100).toFixed(1)}%`}
            {isSample && <span className="ml-1 text-amber-500">· Demo data</span>}
          </p>
        </div>
        {isConnected && (
          <button
            type="button"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="p-1 rounded hover:bg-surface-hover text-text-muted disabled:opacity-40"
            aria-label="Refresh arbitrage scan"
          >
            {isFetching ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          </button>
        )}
      </div>

      {/* Scan parameters */}
      <div className="flex items-center gap-2">
        <Input
          value={universeInput}
          onChange={(e) => setUniverseInput(e.target.value)}
          placeholder="Universe (comma-separated scrips)"
          aria-label="Scan universe, comma-separated scrips"
          className="flex-1 min-w-40 h-7 text-xs"
          disabled={!isConnected}
        />
        <label className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-text-muted">
          Edge %
          <Input
            type="number"
            value={thresholdInput}
            onChange={(e) => setThresholdInput(e.target.value)}
            min={0}
            step={0.1}
            aria-label="Minimum annualised edge percentage"
            className="w-16 h-7 text-xs"
            disabled={!isConnected}
          />
        </label>
      </div>

      {isConnected && isLoading ? (
        <div className="flex-1 flex items-center justify-center gap-2 text-text-muted">
          <Loader2 size={16} className="animate-spin" />
          Scanning live quotes...
        </div>
      ) : isConnected && isError ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-1 text-center px-4">
          <AlertCircle size={18} className="text-loss" aria-hidden="true" />
          <span className="text-loss">
            {error instanceof Error ? error.message : "Arbitrage scan failed"}
          </span>
          <span className="text-[10px] text-text-muted">
            The scan needs live quotes for the universe — nothing fabricated is shown.
          </span>
        </div>
      ) : isConnected && universe.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-text-muted text-center px-4">
          Add scrips to the universe to run a scan.
        </div>
      ) : isRealEmptyScan ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-1 text-center px-4">
          <SearchX size={18} className="text-text-disabled" aria-hidden="true" />
          <span className="text-text-muted">No arbitrage opportunities found.</span>
        </div>
      ) : response !== undefined ? (
        <ScanTables response={response} />
      ) : (
        <div className="flex-1 flex items-center justify-center text-text-muted">
          No scan data yet.
        </div>
      )}
    </div>
  );

  return isConnected ? (
    content
  ) : (
    <FeatureTeaser status="preview" featureName="Arbitrage Scanner" version={APP_VERSION_TAG}>
      {content}
    </FeatureTeaser>
  );
}

export default memo(ArbitrageScannerWidget);
