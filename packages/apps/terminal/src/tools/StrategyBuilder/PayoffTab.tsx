// PayoffTab — payoff diagram, summary cards and payoff table
// Extracted from StrategyBuilderTool.tsx

import { useMemo } from "react";
import { AlertCircle, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  SAMPLE_PREMIUM_HELPER,
  UNSET_PREMIUM_HELPER,
  ZERO_PREMIUM_WARNING,
  validateLegs,
  calculateNetPremium,
  computePayoff,
  computePayoffSummary,
  estimateMargin,
  formatINR,
  hasExplicitZeroPremium,
  hasUnsetPremium,
} from "./utils";
import type { Leg, Underlying } from "./types";

interface Props {
  legs: Leg[];
  atm: number;
  underlying: Underlying;
}

function dashCard(label: string) {
  return (
    <Card className="bg-surface-card border-border-default">
      <CardContent className="p-3">
        <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">{label}</div>
        <div className="text-base font-bold font-mono tabular-nums text-text-muted">—</div>
      </CardContent>
    </Card>
  );
}

export function PayoffTab({ legs, atm, underlying }: Props) {
  const { valid } = validateLegs(legs);
  const premiumUnset = hasUnsetPremium(legs);
  const explicitZero = hasExplicitZeroPremium(legs);
  const sampleSeeded = legs.some((leg) => leg.premiumSource === "sample");
  const spotPrice = atm > 0 ? atm : 20000;
  const points = useMemo(
    () => (valid && !premiumUnset ? computePayoff(legs, spotPrice) : []),
    [legs, valid, spotPrice, premiumUnset],
  );
  const summary = useMemo(
    () => (premiumUnset ? null : computePayoffSummary(legs)),
    [legs, premiumUnset],
  );

  // Chart scale stays on the sampled window; the summary cards use the
  // analytical kinks so unbounded legs are not capped at ±15% of spot.
  const sampledMax = points.length ? Math.max(...points.map((p) => p.pnl)) : 0;
  const sampledMin = points.length ? Math.min(...points.map((p) => p.pnl)) : 0;
  const range = Math.max(Math.abs(sampledMax), Math.abs(sampledMin), 1);
  const maxPnl = summary?.maxProfit ?? null;
  const minPnl = summary?.maxLoss ?? null;
  const bepPoints = summary?.breakevens ?? [];

  const netPremium = calculateNetPremium(legs);

  if (!valid || legs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-text-muted">
        <TrendingUp size={40} />
        <p className="text-xs">Add valid legs to see payoff diagram</p>
      </div>
    );
  }

  if (premiumUnset) {
    return (
      <div className="flex-1 overflow-auto px-3 py-2 space-y-3">
        <div className="grid grid-cols-4 gap-2">
          {dashCard("Max Profit")}
          {dashCard("Max Loss")}
          {dashCard("Net Premium")}
          {dashCard("BEP(s)")}
        </div>
        <p className="text-xs text-text-muted">{UNSET_PREMIUM_HELPER}</p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto px-3 py-2 space-y-3">
      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-2">
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">Max Profit</div>
            <div className={`text-base font-bold font-mono tabular-nums ${(maxPnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {maxPnl === Infinity ? "Unlimited" : formatINR((maxPnl ?? 0) * underlying.lotSize)}
            </div>
          </CardContent>
        </Card>
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">Max Loss</div>
            <div className={`text-base font-bold font-mono tabular-nums ${(minPnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {minPnl === -Infinity ? "Unlimited" : formatINR((minPnl ?? 0) * underlying.lotSize)}
            </div>
          </CardContent>
        </Card>
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">Net Premium</div>
            <div className={`text-base font-bold font-mono tabular-nums ${(netPremium ?? 0) <= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {formatINR(netPremium ?? 0)}
            </div>
            <div className="text-xxs text-text-muted">{(netPremium ?? 0) <= 0 ? "Credit" : "Debit"}</div>
          </CardContent>
        </Card>
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">BEP(s)</div>
            <div className="text-sm font-mono text-text-primary">
              {bepPoints.length === 0 ? "None" : bepPoints.map((b) => b.toFixed(0)).join(", ")}
            </div>
          </CardContent>
        </Card>
      </div>

      {sampleSeeded && (
        <Badge variant="outline" className="text-xxs border-border-default text-text-muted font-normal">
          {SAMPLE_PREMIUM_HELPER}
        </Badge>
      )}
      {explicitZero && (
        <div
          role="alert"
          className="flex items-start gap-1.5 rounded border border-amber-500/30 bg-amber-900/20 px-2 py-1.5 text-xs text-amber-300"
        >
          <AlertCircle size={11} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>{ZERO_PREMIUM_WARNING}</span>
        </div>
      )}

      {/* Visual payoff chart */}
      <Card className="bg-surface-card border-border-default">
        <CardHeader className="p-3 pb-1">
          <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
            Payoff at Expiry
          </CardTitle>
        </CardHeader>
        <CardContent className="p-3 pt-1">
          <div className="relative h-40 flex items-center">
            {/* Zero axis */}
            <div
              className="absolute left-0 right-0 h-px bg-surface-active"
              style={{ top: `${(sampledMax / (range * 2)) * 100 + 50}%` }}
            />
            {/* Bars */}
            <div className="w-full h-full flex items-center gap-px">
              {points.map((pt, i) => {
                const isProfit = pt.pnl >= 0;
                const h = (Math.abs(pt.pnl) / range) * 50;
                const isAtm =
                  Math.abs(pt.price - spotPrice) < (points[1]?.price - points[0]?.price) / 2;
                return (
                  <div
                    key={i}
                    className="flex-1 relative flex flex-col items-center justify-center"
                    style={{ height: "100%" }}
                  >
                    {isProfit ? (
                      <div className="absolute bottom-1/2 w-full flex flex-col-reverse items-center">
                        <div
                          className={`w-full ${isAtm ? "bg-blue-500/80" : "bg-emerald-600/70"} rounded-sm`}
                          style={{ height: `${Math.max(2, h)}px` }}
                          title={`${pt.price.toFixed(0)}: ${formatINR(pt.pnl * underlying.lotSize)}`}
                        />
                      </div>
                    ) : (
                      <div className="absolute top-1/2 w-full flex flex-col items-center">
                        <div
                          className={`w-full ${isAtm ? "bg-blue-500/80" : "bg-red-600/70"} rounded-sm`}
                          style={{ height: `${Math.max(2, h)}px` }}
                          title={`${pt.price.toFixed(0)}: ${formatINR(pt.pnl * underlying.lotSize)}`}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
          {/* x-axis labels */}
          <div className="flex justify-between mt-1">
            <span className="text-xxs text-text-muted">{points[0]?.price.toFixed(0)}</span>
            <span className="text-xxs text-primary">ATM {spotPrice}</span>
            <span className="text-xxs text-text-muted">{points[points.length - 1]?.price.toFixed(0)}</span>
          </div>
        </CardContent>
      </Card>

      {/* Payoff table */}
      <Card className="bg-surface-card border-border-default">
        <CardHeader className="p-3 pb-1">
          <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
            Payoff Table (per lot)
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-auto max-h-48">
            <Table>
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent sticky top-0 bg-surface-card">
                  <TableHead className="text-xs text-text-muted h-7 pl-3 font-normal">Price</TableHead>
                  <TableHead className="text-xs text-text-muted h-7 text-right font-normal">P&L (1 lot)</TableHead>
                  <TableHead className="text-xs text-text-muted h-7 text-right pr-3 font-normal">% of Margin</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {points.filter((_, i) => i % 4 === 0).map((pt, i) => {
                  const pnlLot = pt.pnl * underlying.lotSize;
                  const margin = estimateMargin(legs, underlying);
                  const pct = margin > 0 ? (pnlLot / margin) * 100 : 0;
                  const isAtm =
                    Math.abs(pt.price - spotPrice) < (points[4]?.price - points[0]?.price) / 2;
                  return (
                    <TableRow
                      key={i}
                      className={`border-border-subtle hover:bg-surface-base ${isAtm ? "bg-surface-elevated" : ""}`}
                    >
                      <TableCell className={`py-1 pl-3 text-xs font-mono ${isAtm ? "text-primary font-medium" : "text-text-secondary"}`}>
                        {pt.price.toFixed(0)}
                        {isAtm && <span className="text-xxs ml-1 text-primary">ATM</span>}
                      </TableCell>
                      <TableCell className={`py-1 text-xs font-mono text-right ${pnlLot >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {pnlLot >= 0 ? "+" : ""}{formatINR(pnlLot)}
                      </TableCell>
                      <TableCell className={`py-1 text-xs font-mono text-right pr-3 ${pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {pct >= 0 ? "+" : ""}{pct.toFixed(1)}%
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
