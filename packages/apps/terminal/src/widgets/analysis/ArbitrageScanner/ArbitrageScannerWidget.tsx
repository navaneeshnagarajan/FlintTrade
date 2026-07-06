/**
 * ArbitrageScannerWidget — cash-future & cross-exchange arbitrage scanner (DP3).
 *
 * Two ranked tables:
 *   - Cash-future basis dislocations: observed basis (future − spot) vs the
 *     fair cost-of-carry, with the annualised carry yield and a cash-and-carry
 *     / reverse / fair signal.
 *   - Cross-exchange price gaps: same scrip on NSE vs BSE, with the buy/sell leg.
 *
 * Read-only analytics — no order placement. Until a live cash+future universe
 * feed is wired the scan is representative sample data, always marked "Demo
 * data"; the badge clears automatically once the backend serves a live scan.
 */

import { memo } from "react";
import { RefreshCw, Loader2, ArrowLeftRight, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { useArbitrageScanner } from "./useArbitrageScanner";
import { SAMPLE_ARBITRAGE_SCAN } from "./sampleData";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { APP_VERSION_TAG } from "@/lib/appVersion";
import type { ArbSignal, CashFutureOpportunity, CrossExchangeOpportunity } from "@/types/api";

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

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

function ArbitrageScannerWidget() {
  const isConnected = useBrokerConnected();
  const { data: live, isLoading, isFetching, refetch } = useArbitrageScanner(isConnected);

  const response = isConnected && live ? live : { is_sample_data: true, scan: SAMPLE_ARBITRAGE_SCAN };
  const scan = response.scan;
  const isSample = response.is_sample_data;

  const content = (
    <div className="flex flex-col h-full gap-3 p-3 text-xs">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-1.5">
            <ArrowLeftRight size={14} /> Arbitrage Scanner
          </h3>
          <p className="text-[10px] text-text-muted">
            Cash-future basis &amp; cross-exchange · funding {(scan.risk_free_rate * 100).toFixed(1)}%
            {isSample && <span className="ml-1 text-amber-500">· Demo data</span>}
          </p>
        </div>
        {isConnected && (
          <button
            type="button"
            onClick={() => void refetch()}
            className="p-1 rounded hover:bg-surface-hover text-text-muted"
            aria-label="Refresh arbitrage scan"
          >
            {isFetching ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          </button>
        )}
      </div>

      {isLoading && isConnected ? (
        <div className="flex-1 flex items-center justify-center text-text-muted">
          <Loader2 size={16} className="animate-spin" />
        </div>
      ) : (
        <div className="flex-1 overflow-auto space-y-4">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-text-muted mb-1">Cash-future basis</div>
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
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wide text-text-muted mb-1">Cross-exchange gaps</div>
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
          </div>
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
