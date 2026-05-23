// MarginTab — SPAN margin estimate and leg-wise breakdown
// Extracted from StrategyBuilderTool.tsx

import { useMemo } from "react";
import { Zap } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { validateLegs, calculateNetPremium, estimateMargin, formatINR } from "./utils";
import type { Leg, Underlying } from "./types";

interface Props {
  legs: Leg[];
  underlying: Underlying;
}

export function MarginTab({ legs, underlying }: Props) {
  const { valid } = validateLegs(legs);
  const margin = useMemo(() => (valid ? estimateMargin(legs, underlying) : 0), [legs, valid, underlying]);
  const netPremium = calculateNetPremium(legs);
  const premiumCollected = netPremium < 0 ? Math.abs(netPremium) * underlying.lotSize : 0;
  const premiumPaid = netPremium > 0 ? netPremium * underlying.lotSize : 0;
  const effectiveMargin = margin - premiumCollected;

  if (!valid || legs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-text-muted">
        <Zap size={40} />
        <p className="text-xs">Add valid legs to see margin estimate</p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto px-3 py-2 space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">SPAN Margin (est.)</div>
            <div className="text-xl font-bold font-mono tabular-nums text-text-primary">{formatINR(margin)}</div>
            <div className="text-xs text-text-muted mt-0.5">Selling positions only</div>
          </CardContent>
        </Card>
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">Effective Margin</div>
            <div className="text-xl font-bold font-mono tabular-nums text-emerald-400">{formatINR(effectiveMargin)}</div>
            <div className="text-xs text-text-muted mt-0.5">After premium credit/debit</div>
          </CardContent>
        </Card>
      </div>

      <Card className="bg-surface-card border-border-default">
        <CardHeader className="p-3 pb-1">
          <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
            Leg-wise Breakdown
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="border-border-default hover:bg-transparent">
                <TableHead className="text-xs text-text-muted h-7 pl-3 font-normal">Leg</TableHead>
                <TableHead className="text-xs text-text-muted h-7 font-normal">Action</TableHead>
                <TableHead className="text-xs text-text-muted h-7 font-normal">Type</TableHead>
                <TableHead className="text-xs text-text-muted h-7 text-right font-normal">Strike</TableHead>
                <TableHead className="text-xs text-text-muted h-7 text-right font-normal">Lots</TableHead>
                <TableHead className="text-xs text-text-muted h-7 text-right pr-3 font-normal">Margin</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {legs.map((leg, idx) => {
                const legMargin =
                  leg.action === "SELL"
                    ? 0.15 * 20000 * leg.lots * underlying.lotSize
                    : leg.premium * leg.lots * underlying.lotSize;
                return (
                  <TableRow key={leg.id} className="border-border-subtle hover:bg-surface-base">
                    <TableCell className="py-1 pl-3 text-xs text-text-muted">{idx + 1}</TableCell>
                    <TableCell className="py-1">
                      <Badge
                        variant="outline"
                        className={`text-xxs px-1.5 py-0 border-0 ${leg.action === "BUY" ? "bg-emerald-900/40 text-emerald-400" : "bg-red-900/40 text-red-400"}`}
                      >
                        {leg.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="py-1 text-xs text-text-secondary">{leg.optionType}</TableCell>
                    <TableCell className="py-1 text-xs font-mono text-text-secondary text-right">{leg.strike}</TableCell>
                    <TableCell className="py-1 text-xs font-mono text-text-secondary text-right">{leg.lots}</TableCell>
                    <TableCell className="py-1 text-xs font-mono text-right pr-3 text-text-primary">{formatINR(legMargin)}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card className="bg-surface-card border-border-default">
        <CardContent className="p-3 space-y-1.5">
          {[
            { label: "Premium Paid",      value: formatINR(premiumPaid),      color: "text-red-400"     },
            { label: "Premium Collected", value: formatINR(premiumCollected), color: "text-emerald-400" },
            { label: "Lot Size",          value: String(underlying.lotSize),  color: "text-text-primary" },
            { label: "Total Lots",        value: String(legs.reduce((s, l) => s + l.lots, 0)), color: "text-text-primary" },
          ].map(({ label, value, color }) => (
            <div key={label} className="flex justify-between items-center">
              <span className="text-xs text-text-muted">{label}</span>
              <span className={`text-xs font-mono font-medium ${color}`}>{value}</span>
            </div>
          ))}
          <div className="border-t border-border-default pt-1.5 flex justify-between items-center">
            <span className="text-xs text-text-secondary font-medium">Total Capital Required</span>
            <span className="text-sm font-mono font-bold text-text-primary">{formatINR(effectiveMargin)}</span>
          </div>
          <p className="text-xxs text-text-muted mt-1">
            Estimate only. Actual SPAN margin may differ. Use broker margin calculator for exact values.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
