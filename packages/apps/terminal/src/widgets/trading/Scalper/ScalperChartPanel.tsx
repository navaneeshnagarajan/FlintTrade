// ─── Scalper — 3-panel chart area (CE / Spot / PE) ───────────────────────────

import { RefreshCw, TrendingDown, TrendingUp, X } from "lucide-react";
import Chart from "@/components/Chart";
import { ActionButton, LtpBlock } from "./ScalperPrimitives";
import { fmtInt } from "./helpers";
import type { IntervalValue, OrderAction, TickMap } from "./types";

export interface ScalperChartPanelProps {
  symbol: string;
  spotExch: string;
  optExch: string;
  ceSymbol: string | null;
  peSymbol: string | null;
  ceStrike: number | null;
  peStrike: number | null;
  atmStrike: number | null;
  lots: number;
  interval: IntervalValue;
  ticks: TickMap;
  onOrder: (sym: string | null, exch: string, action: OrderAction) => void;
  onCloseAll: () => void;
  onCancelAll: () => void;
}

export function ScalperChartPanel({
  symbol,
  spotExch,
  optExch,
  ceSymbol,
  peSymbol,
  ceStrike,
  peStrike,
  atmStrike,
  lots,
  interval,
  ticks,
  onOrder,
  onCloseAll,
  onCancelAll,
}: ScalperChartPanelProps) {
  const chartHeight = 120;

  return (
    <div className="flex-1 flex min-h-0 overflow-hidden">
      {/* CE PANEL */}
      <div
        className="flex flex-col border-r border-border-default"
        style={{ width: "28%", minWidth: 0 }}
      >
        {/* CE header */}
        <div className="shrink-0 px-3 py-2 bg-surface-card border-b border-border-subtle">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-mono text-profit font-bold uppercase tracking-wider">
              {ceSymbol ?? `${symbol} CE`}
            </span>
            <span className="text-xxs text-text-disabled font-sans uppercase">Call</span>
          </div>
          <LtpBlock
            label="LTP"
            symbol={ceSymbol ?? ""}
            exchange={optExch}
            ticks={ticks}
          />
        </div>

        {/* CE chart */}
        <div className="flex-1 overflow-hidden min-h-0">
          {ceSymbol ? (
            <Chart
              symbol={ceSymbol}
              exchange={optExch}
              interval={interval}
              height={chartHeight}
              className="h-full"
            />
          ) : (
            <div className="h-full flex items-center justify-center text-xs text-text-muted font-sans">
              Select expiry
            </div>
          )}
        </div>

        {/* CE action buttons */}
        <div className="shrink-0 flex border-t border-border-default">
          <ActionButton
            onClick={() => onOrder(ceSymbol, optExch, "SELL")}
            disabled={!ceSymbol}
            title="Sell CE (Shift+←)"
            variant="sell"
            icon={<TrendingDown size={14} />}
            label="Sell CE"
            shortcut="Shift + ←"
            aria-label={`Sell CE ${ceSymbol ?? symbol} ${ceStrike ?? ""} ${lots} lot${lots > 1 ? "s" : ""}`}
          />
          <ActionButton
            onClick={() => onOrder(ceSymbol, optExch, "BUY")}
            disabled={!ceSymbol}
            title="Buy CE (Shift+↑)"
            variant="buy"
            icon={<TrendingUp size={14} />}
            label="Buy CE"
            shortcut="Shift + ↑"
            aria-label={`Buy CE ${ceSymbol ?? symbol} ${ceStrike ?? ""} ${lots} lot${lots > 1 ? "s" : ""}`}
          />
        </div>
      </div>

      {/* SPOT PANEL */}
      <div className="flex flex-col" style={{ width: "44%", minWidth: 0 }}>
        {/* Spot header */}
        <div className="shrink-0 px-3 py-2 bg-surface-card border-b border-border-subtle">
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-baseline gap-2">
              <span className="text-sm font-heading font-bold text-text-primary">
                {symbol}
              </span>
              <span className="text-xxs text-text-disabled font-sans uppercase">{spotExch}</span>
            </div>
            <span className="text-xs font-mono text-text-primary uppercase">Spot</span>
          </div>
          <div className="flex items-center gap-4">
            <LtpBlock label="LTP" symbol={symbol} exchange={spotExch} ticks={ticks} />
            {atmStrike != null && (
              <div className="flex items-baseline gap-1">
                <span className="text-xxs text-text-muted uppercase tracking-wider font-sans">ATM</span>
                <span className="font-mono text-sm font-bold text-accent">{fmtInt(atmStrike)}</span>
              </div>
            )}
          </div>
        </div>

        {/* Spot chart */}
        <div className="flex-1 overflow-hidden min-h-0">
          <Chart
            symbol={symbol}
            exchange={spotExch}
            interval={interval}
            height={chartHeight}
            className="h-full"
          />
        </div>

        {/* Center action buttons: Close All / Cancel All */}
        <div className="shrink-0 flex border-t border-border-default">
          <ActionButton
            onClick={onCloseAll}
            title="Close all positions (F6)"
            variant="warning"
            icon={<X size={14} />}
            label="Close All"
            shortcut="F6"
          />
          <ActionButton
            onClick={onCancelAll}
            title="Cancel all orders (F7)"
            variant="neutral"
            icon={<RefreshCw size={14} />}
            label="Cancel All"
            shortcut="F7"
          />
        </div>
      </div>

      {/* PE PANEL */}
      <div
        className="flex flex-col border-l border-border-default"
        style={{ width: "28%", minWidth: 0 }}
      >
        {/* PE header */}
        <div className="shrink-0 px-3 py-2 bg-surface-card border-b border-border-subtle">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-mono text-loss font-bold uppercase tracking-wider">
              {peSymbol ?? `${symbol} PE`}
            </span>
            <span className="text-xxs text-text-disabled font-sans uppercase">Put</span>
          </div>
          <LtpBlock
            label="LTP"
            symbol={peSymbol ?? ""}
            exchange={optExch}
            ticks={ticks}
          />
        </div>

        {/* PE chart */}
        <div className="flex-1 overflow-hidden min-h-0">
          {peSymbol ? (
            <Chart
              symbol={peSymbol}
              exchange={optExch}
              interval={interval}
              height={chartHeight}
              className="h-full"
            />
          ) : (
            <div className="h-full flex items-center justify-center text-xs text-text-muted font-sans">
              Select expiry
            </div>
          )}
        </div>

        {/* PE action buttons */}
        <div className="shrink-0 flex border-t border-border-default">
          <ActionButton
            onClick={() => onOrder(peSymbol, optExch, "BUY")}
            disabled={!peSymbol}
            title="Buy Put (Shift+↓)"
            variant="buy"
            icon={<TrendingUp size={14} />}
            label="Buy PE"
            shortcut="Shift + ↓"
            aria-label={`Buy PE ${peSymbol ?? symbol} ${peStrike ?? ""} ${lots} lot${lots > 1 ? "s" : ""}`}
          />
          <ActionButton
            onClick={() => onOrder(peSymbol, optExch, "SELL")}
            disabled={!peSymbol}
            title="Sell Put (Shift+→)"
            variant="sell"
            icon={<TrendingDown size={14} />}
            label="Sell PE"
            shortcut="Shift + →"
            aria-label={`Sell PE ${peSymbol ?? symbol} ${peStrike ?? ""} ${lots} lot${lots > 1 ? "s" : ""}`}
          />
        </div>
      </div>
    </div>
  );
}
