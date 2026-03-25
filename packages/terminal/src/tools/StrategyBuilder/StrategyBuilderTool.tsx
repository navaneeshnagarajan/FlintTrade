// Absorbed patterns from:
//   openalgo-chart/src/components/OptionChainPicker/OptionChainPicker.jsx — multi-leg state, strategy templates, direction (buy/sell), net premium calc
//   openalgo-chart/src/services/strategyTemplates.js — STRATEGY_TEMPLATES, calculateNetPremium, validateStrategy, formatStrategyName

import { useState, useMemo, useRef } from "react";
import { Brain, X, Plus, Trash2, AlertCircle, TrendingUp, Zap, Code2, Play, RotateCcw, ChevronDown, ChevronUp, Copy, Check } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePineRunner } from "./usePineRunner";
import type { PineRunnerOptions } from "./usePineRunner";

interface Props {
  onClose?: () => void;
}

// ---- Types absorbed from strategyTemplates.js ----

type OptionType = "CE" | "PE";
type Direction = "BUY" | "SELL";

interface Leg {
  id: string;
  action: Direction;
  optionType: OptionType;
  strike: number;
  lots: number;
  premium: number;
}

// STRATEGY_TEMPLATES absorbed from openalgo-chart/src/services/strategyTemplates.js
const STRATEGY_TEMPLATES: Record<string, { name: string; description: string; legs: { action: Direction; optionType: OptionType; strikeOffset: number; lots: number }[] }> = {
  straddle: {
    name: "Straddle",
    description: "Buy ATM CE + Buy ATM PE (same strike)",
    legs: [
      { action: "BUY", optionType: "CE", strikeOffset: 0, lots: 1 },
      { action: "BUY", optionType: "PE", strikeOffset: 0, lots: 1 },
    ],
  },
  strangle: {
    name: "Strangle",
    description: "Buy OTM CE + Buy OTM PE (different strikes)",
    legs: [
      { action: "BUY", optionType: "CE", strikeOffset: 1, lots: 1 },
      { action: "BUY", optionType: "PE", strikeOffset: -1, lots: 1 },
    ],
  },
  "short-straddle": {
    name: "Short Straddle",
    description: "Sell ATM CE + Sell ATM PE (theta decay)",
    legs: [
      { action: "SELL", optionType: "CE", strikeOffset: 0, lots: 1 },
      { action: "SELL", optionType: "PE", strikeOffset: 0, lots: 1 },
    ],
  },
  "iron-condor": {
    name: "Iron Condor",
    description: "Sell OTM strangle, buy protection",
    legs: [
      { action: "BUY", optionType: "PE", strikeOffset: -2, lots: 1 },
      { action: "SELL", optionType: "PE", strikeOffset: -1, lots: 1 },
      { action: "SELL", optionType: "CE", strikeOffset: 1, lots: 1 },
      { action: "BUY", optionType: "CE", strikeOffset: 2, lots: 1 },
    ],
  },
  butterfly: {
    name: "Butterfly",
    description: "Buy ITM, Sell 2 ATM, Buy OTM CE",
    legs: [
      { action: "BUY", optionType: "CE", strikeOffset: -1, lots: 1 },
      { action: "SELL", optionType: "CE", strikeOffset: 0, lots: 2 },
      { action: "BUY", optionType: "CE", strikeOffset: 1, lots: 1 },
    ],
  },
  "bull-call-spread": {
    name: "Bull Call Spread",
    description: "Buy lower strike CE, Sell higher strike CE",
    legs: [
      { action: "BUY", optionType: "CE", strikeOffset: 0, lots: 1 },
      { action: "SELL", optionType: "CE", strikeOffset: 1, lots: 1 },
    ],
  },
  "bear-put-spread": {
    name: "Bear Put Spread",
    description: "Buy higher strike PE, Sell lower strike PE",
    legs: [
      { action: "BUY", optionType: "PE", strikeOffset: 0, lots: 1 },
      { action: "SELL", optionType: "PE", strikeOffset: -1, lots: 1 },
    ],
  },
};

// Absorbed from strategyTemplates.js — calculateNetPremium
function calculateNetPremium(legs: Leg[]): number {
  return legs.reduce((total, leg) => {
    const multiplier = leg.action === "BUY" ? 1 : -1;
    return total + multiplier * leg.lots * leg.premium;
  }, 0);
}

// Absorbed from strategyTemplates.js — validateStrategy
function validateLegs(legs: Leg[]): { valid: boolean; error: string | null } {
  if (legs.length < 1) return { valid: false, error: "Add at least one leg" };
  if (legs.length > 6) return { valid: false, error: "Maximum 6 legs allowed" };
  for (let i = 0; i < legs.length; i++) {
    if (legs[i].strike <= 0) return { valid: false, error: `Leg ${i + 1}: strike must be > 0` };
    if (legs[i].lots < 1) return { valid: false, error: `Leg ${i + 1}: lots must be >= 1` };
    if (legs[i].premium < 0) return { valid: false, error: `Leg ${i + 1}: premium must be >= 0` };
  }
  return { valid: true, error: null };
}

function genId(): string {
  return `leg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function formatINR(v: number): string {
  if (isNaN(v)) return "₹0.00";
  return `${v < 0 ? "-" : ""}₹${Math.abs(v).toFixed(2)}`;
}

// ---- Default underlyings for Indian F&O ----
const UNDERLYINGS = [
  { symbol: "NIFTY", exchange: "NSE_INDEX", lotSize: 25, strikeGap: 50 },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX", lotSize: 15, strikeGap: 100 },
  { symbol: "FINNIFTY", exchange: "NSE_INDEX", lotSize: 40, strikeGap: 50 },
  { symbol: "MIDCPNIFTY", exchange: "NSE_INDEX", lotSize: 75, strikeGap: 25 },
  { symbol: "SENSEX", exchange: "BSE_INDEX", lotSize: 10, strikeGap: 100 },
];

// ---- Payoff computation ----
interface PayoffPoint {
  price: number;
  pnl: number;
}

function computePayoff(legs: Leg[], spotPrice: number): PayoffPoint[] {
  const range = spotPrice * 0.15;
  const steps = 40;
  const step = (range * 2) / steps;
  const points: PayoffPoint[] = [];

  for (let i = 0; i <= steps; i++) {
    const price = spotPrice - range + i * step;
    let pnl = 0;
    for (const leg of legs) {
      const multiplier = leg.action === "BUY" ? 1 : -1;
      let intrinsic = 0;
      if (leg.optionType === "CE") {
        intrinsic = Math.max(0, price - leg.strike);
      } else {
        intrinsic = Math.max(0, leg.strike - price);
      }
      pnl += multiplier * leg.lots * (intrinsic - leg.premium);
    }
    points.push({ price, pnl });
  }
  return points;
}

// SPAN margin estimate (simplified — absorbed from openalgo-chart PositionTracker margin concept)
function estimateMargin(legs: Leg[], underlying: typeof UNDERLYINGS[0]): number {
  // Simplified: selling options requires SPAN + Exposure margin
  // Use 15% of notional for sold options, 100% premium for bought
  const notionalPerUnit = 20000; // approximate index unit value for NIFTY
  let margin = 0;
  for (const leg of legs) {
    if (leg.action === "SELL") {
      margin += 0.15 * notionalPerUnit * leg.lots * underlying.lotSize;
    } else {
      margin += leg.premium * leg.lots * underlying.lotSize;
    }
  }
  return margin;
}

// ---- Sub-tabs ----

function LegsTab({
  legs,
  onAdd,
  onRemove,
  onChange,
  onTemplate,
  atm,
  onAtmChange,
  underlying,
  onUnderlyingChange,
  strikeGap,
  onStrikeGapChange,
}: {
  legs: Leg[];
  onAdd: () => void;
  onRemove: (id: string) => void;
  onChange: (id: string, field: keyof Leg, value: unknown) => void;
  onTemplate: (key: string) => void;
  atm: number;
  onAtmChange: (v: number) => void;
  underlying: typeof UNDERLYINGS[0];
  onUnderlyingChange: (symbol: string) => void;
  strikeGap: number;
  onStrikeGapChange: (v: number) => void;
}) {
  const { valid, error } = validateLegs(legs);
  const netPremium = calculateNetPremium(legs);
  const isDebit = netPremium > 0;

  return (
    <div className="flex flex-col h-full gap-2">
      {/* Config bar */}
      <div className="flex items-center gap-2 px-3 pt-2 flex-wrap">
        <Select value={underlying.symbol} onValueChange={onUnderlyingChange}>
          <SelectTrigger className="w-28 h-7 text-xs bg-surface-base border-border-default text-text-primary">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-surface-card border-border-default text-text-primary">
            {UNDERLYINGS.map((u) => (
              <SelectItem key={u.symbol} value={u.symbol} className="text-xs hover:bg-surface-elevated">{u.symbol}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="flex items-center gap-1">
          <span className="text-xs text-text-muted">ATM</span>
          <Input
            className="w-20 h-7 text-xs bg-surface-base border-border-default text-text-primary font-mono"
            type="number"
            value={atm}
            onChange={(e) => onAtmChange(Number(e.target.value))}
          />
        </div>

        <div className="flex items-center gap-1">
          <span className="text-xs text-text-muted">Gap</span>
          <Input
            className="w-16 h-7 text-xs bg-surface-base border-border-default text-text-primary font-mono"
            type="number"
            value={strikeGap}
            onChange={(e) => onStrikeGapChange(Number(e.target.value))}
          />
        </div>

        {legs.length > 0 && (
          <Badge
            variant="outline"
            className={`text-xxs px-1.5 border-0 font-mono ml-auto ${isDebit ? "bg-red-900/40 text-red-400" : "bg-emerald-900/40 text-emerald-400"}`}
          >
            {isDebit ? "Debit" : "Credit"} {formatINR(Math.abs(netPremium))}
          </Badge>
        )}
      </div>

      {/* Template quick-apply bar — absorbed from OptionChainPicker strategy template buttons */}
      <div className="flex items-center gap-1 px-3 flex-wrap">
        {Object.entries(STRATEGY_TEMPLATES).map(([key, tmpl]) => (
          <Button
            key={key}
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xs text-text-muted hover:text-text-primary hover:bg-surface-elevated border border-border-default"
            onClick={() => onTemplate(key)}
            title={tmpl.description}
          >
            {tmpl.name}
          </Button>
        ))}
      </div>

      {/* Legs table */}
      <div className="flex-1 overflow-auto px-3">
        {legs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 gap-2 text-text-muted">
            <Brain size={32} />
            <p className="text-xs">Click a template or add legs manually</p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="border-border-default hover:bg-transparent">
                <TableHead className="text-xs text-text-muted h-7 font-normal">#</TableHead>
                <TableHead className="text-xs text-text-muted h-7 font-normal">Action</TableHead>
                <TableHead className="text-xs text-text-muted h-7 font-normal">Type</TableHead>
                <TableHead className="text-xs text-text-muted h-7 font-normal text-right">Strike</TableHead>
                <TableHead className="text-xs text-text-muted h-7 font-normal text-right">Lots</TableHead>
                <TableHead className="text-xs text-text-muted h-7 font-normal text-right">Premium</TableHead>
                <TableHead className="text-xs text-text-muted h-7 font-normal text-right">Net</TableHead>
                <TableHead className="text-xs text-text-muted h-7 font-normal" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {legs.map((leg, idx) => {
                const net = (leg.action === "BUY" ? 1 : -1) * leg.lots * leg.premium;
                return (
                  <TableRow key={leg.id} className="border-border-subtle hover:bg-surface-base">
                    <TableCell className="py-1 text-xs text-text-muted">{idx + 1}</TableCell>
                    <TableCell className="py-1">
                      <Select
                        value={leg.action}
                        onValueChange={(v) => onChange(leg.id, "action", v as Direction)}
                      >
                        <SelectTrigger className={`w-16 h-6 text-xs border-0 font-medium ${leg.action === "BUY" ? "bg-emerald-900/40 text-emerald-400" : "bg-red-900/40 text-red-400"}`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-surface-card border-border-default text-text-primary">
                          <SelectItem value="BUY" className="text-xs hover:bg-surface-elevated text-emerald-400">BUY</SelectItem>
                          <SelectItem value="SELL" className="text-xs hover:bg-surface-elevated text-red-400">SELL</SelectItem>
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell className="py-1">
                      <Select
                        value={leg.optionType}
                        onValueChange={(v) => onChange(leg.id, "optionType", v as OptionType)}
                      >
                        <SelectTrigger className="w-14 h-6 text-xs bg-surface-base border-border-default text-text-primary">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-surface-card border-border-default text-text-primary">
                          <SelectItem value="CE" className="text-xs hover:bg-surface-elevated">CE</SelectItem>
                          <SelectItem value="PE" className="text-xs hover:bg-surface-elevated">PE</SelectItem>
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell className="py-1">
                      <Input
                        className="w-20 h-6 text-xs text-right bg-surface-base border-border-default text-text-primary font-mono"
                        type="number"
                        value={leg.strike}
                        onChange={(e) => onChange(leg.id, "strike", Number(e.target.value))}
                      />
                    </TableCell>
                    <TableCell className="py-1">
                      <Input
                        className="w-14 h-6 text-xs text-right bg-surface-base border-border-default text-text-primary font-mono"
                        type="number"
                        min={1}
                        value={leg.lots}
                        onChange={(e) => onChange(leg.id, "lots", Math.max(1, Number(e.target.value)))}
                      />
                    </TableCell>
                    <TableCell className="py-1">
                      <Input
                        className="w-20 h-6 text-xs text-right bg-surface-base border-border-default text-text-primary font-mono"
                        type="number"
                        min={0}
                        step={0.05}
                        value={leg.premium}
                        onChange={(e) => onChange(leg.id, "premium", Math.max(0, Number(e.target.value)))}
                      />
                    </TableCell>
                    <TableCell className={`py-1 text-xs font-mono text-right ${net >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {net >= 0 ? "+" : ""}{net.toFixed(2)}
                    </TableCell>
                    <TableCell className="py-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 w-6 p-0 text-text-muted hover:text-red-400"
                        onClick={() => onRemove(leg.id)}
                      >
                        <Trash2 size={11} />
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center gap-2 px-3 pb-2">
        <Button
          variant="ghost"
          size="sm"
          className="h-7 text-xs border border-border-default text-text-muted hover:text-text-primary hover:bg-surface-elevated"
          onClick={onAdd}
          disabled={legs.length >= 6}
        >
          <Plus size={12} className="mr-1" />Add Leg
        </Button>
        {!valid && error && (
          <span className="text-xs text-red-400 flex items-center gap-1">
            <AlertCircle size={10} />{error}
          </span>
        )}
      </div>
    </div>
  );
}

function PayoffTab({ legs, atm, underlying }: { legs: Leg[]; atm: number; underlying: typeof UNDERLYINGS[0] }) {
  const { valid } = validateLegs(legs);
  const spotPrice = atm > 0 ? atm : 20000;
  const points = useMemo(() => (valid ? computePayoff(legs, spotPrice) : []), [legs, valid, spotPrice]);

  const maxPnl = points.length ? Math.max(...points.map((p) => p.pnl)) : 0;
  const minPnl = points.length ? Math.min(...points.map((p) => p.pnl)) : 0;
  const range = Math.max(Math.abs(maxPnl), Math.abs(minPnl), 1);

  const bepPoints = useMemo(() => {
    const beps: number[] = [];
    for (let i = 1; i < points.length; i++) {
      if ((points[i - 1].pnl < 0 && points[i].pnl >= 0) || (points[i - 1].pnl >= 0 && points[i].pnl < 0)) {
        const bep = points[i - 1].price + ((0 - points[i - 1].pnl) / (points[i].pnl - points[i - 1].pnl)) * (points[i].price - points[i - 1].price);
        beps.push(bep);
      }
    }
    return beps;
  }, [points]);

  const netPremium = calculateNetPremium(legs);

  if (!valid || legs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-text-muted">
        <TrendingUp size={40} />
        <p className="text-xs">Add valid legs to see payoff diagram</p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto px-3 py-2 space-y-3">
      {/* Summary */}
      <div className="grid grid-cols-4 gap-2">
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">Max Profit</div>
            <div className={`text-base font-bold font-mono tabular-nums ${maxPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {maxPnl === Infinity ? "Unlimited" : formatINR(maxPnl * underlying.lotSize)}
            </div>
          </CardContent>
        </Card>
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">Max Loss</div>
            <div className={`text-base font-bold font-mono tabular-nums ${minPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {minPnl === -Infinity ? "Unlimited" : formatINR(minPnl * underlying.lotSize)}
            </div>
          </CardContent>
        </Card>
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">Net Premium</div>
            <div className={`text-base font-bold font-mono tabular-nums ${netPremium <= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {formatINR(netPremium)}
            </div>
            <div className="text-xxs text-text-muted">{netPremium <= 0 ? "Credit" : "Debit"}</div>
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

      {/* Visual payoff chart */}
      <Card className="bg-surface-card border-border-default">
        <CardHeader className="p-3 pb-1">
          <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">Payoff at Expiry</CardTitle>
        </CardHeader>
        <CardContent className="p-3 pt-1">
          <div className="relative h-40 flex items-center">
            {/* Zero axis */}
            <div className="absolute left-0 right-0 h-px bg-surface-active" style={{ top: `${((maxPnl) / (range * 2)) * 100 + 50}%` }} />
            {/* Bars */}
            <div className="w-full h-full flex items-center gap-px">
              {points.map((pt, i) => {
                const isProfit = pt.pnl >= 0;
                const h = Math.abs(pt.pnl) / range * 50;
                const isAtm = Math.abs(pt.price - spotPrice) < (points[1]?.price - points[0]?.price) / 2;
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
          <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">Payoff Table (per lot)</CardTitle>
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
                  const isAtm = Math.abs(pt.price - spotPrice) < (points[4]?.price - points[0]?.price) / 2;
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

function MarginTab({ legs, underlying }: { legs: Leg[]; underlying: typeof UNDERLYINGS[0] }) {
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
          <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">Leg-wise Breakdown</CardTitle>
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
                const legMargin = leg.action === "SELL"
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
            { label: "Premium Paid", value: formatINR(premiumPaid), color: "text-red-400" },
            { label: "Premium Collected", value: formatINR(premiumCollected), color: "text-emerald-400" },
            { label: "Lot Size", value: String(underlying.lotSize), color: "text-text-primary" },
            { label: "Total Lots", value: String(legs.reduce((s, l) => s + l.lots, 0)), color: "text-text-primary" },
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

// ---- Pine Script tab ----

// Exchange options aligned with FlintTrade multi-exchange support
const EXCHANGES = [
  "NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX",
  "NSE_INDEX", "BSE_INDEX",
];

// Interval labels — OpenAlgo supported intervals
const INTERVALS = ["1m", "3m", "5m", "10m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"];

// Pine Script template library
const PINE_TEMPLATES: Record<string, { label: string; description: string; code: string }> = {
  ema_crossover: {
    label: "EMA Crossover",
    description: "Fast EMA(20) crosses above/below slow EMA(50)",
    code: `//@version=5
strategy("EMA Crossover", overlay=true)
fast = ta.ema(close, 20)
slow = ta.ema(close, 50)
if ta.crossover(fast, slow)
    strategy.entry("Long", strategy.long)
if ta.crossunder(fast, slow)
    strategy.close("Long")
plot(fast, title="EMA 20", color=color.blue)
plot(slow, title="EMA 50", color=color.red)`,
  },
  sma_crossover: {
    label: "SMA Crossover",
    description: "Fast SMA(20) crosses above/below slow SMA(50)",
    code: `//@version=5
strategy("SMA Crossover", overlay=true)
fast = ta.sma(close, 20)
slow = ta.sma(close, 50)
if ta.crossover(fast, slow)
    strategy.entry("Long", strategy.long)
if ta.crossunder(fast, slow)
    strategy.close("Long")
plot(fast, title="SMA 20", color=color.green)
plot(slow, title="SMA 50", color=color.orange)`,
  },
  rsi_mean_reversion: {
    label: "RSI Mean Reversion",
    description: "Buy when RSI dips below 30, exit when above 70",
    code: `//@version=5
strategy("RSI Mean Reversion", overlay=false)
myRsi = ta.rsi(close, 14)
if myRsi < 30
    strategy.entry("Long", strategy.long)
if myRsi > 70
    strategy.close("Long")
plot(myRsi, title="RSI", color=color.purple)`,
  },
  ema_ribbon: {
    label: "EMA Ribbon",
    description: "Three EMAs — 9, 21, 55. Plot only, no signals.",
    code: `//@version=5
strategy("EMA Ribbon", overlay=true)
e9  = ta.ema(close, 9)
e21 = ta.ema(close, 21)
e55 = ta.ema(close, 55)
plot(e9,  title="EMA 9",  color=color.lime)
plot(e21, title="EMA 21", color=color.blue)
plot(e55, title="EMA 55", color=color.orange)`,
  },
  macd_signal: {
    label: "MACD Signal",
    description: "Entry on MACD crossover the signal line",
    code: `//@version=5
strategy("MACD Signal", overlay=false)
myMacd = ta.macd(close, 12, 26, 9)
if ta.crossover(myMacd, myMacd_signal)
    strategy.entry("Long", strategy.long)
if ta.crossunder(myMacd, myMacd_signal)
    strategy.close("Long")
plot(myMacd,        title="MACD",   color=color.blue)
plot(myMacd_signal, title="Signal", color=color.orange)`,
  },
};

// Equity curve computation from bar closes + signals
interface EquityPoint { bar: number; equity: number }

function computeEquityCurve(
  bars: { close: number }[],
  signals: { bar: number; type: "BUY" | "SELL" }[],
): EquityPoint[] {
  let inTrade = false;
  let entryPrice = 0;
  let equity = 10000; // notional starting capital
  const curve: EquityPoint[] = [{ bar: 0, equity }];

  const signalMap = new Map(signals.map((s) => [s.bar, s.type]));

  for (let i = 1; i < bars.length; i++) {
    const sig = signalMap.get(i);
    if (sig === "BUY" && !inTrade) {
      inTrade = true;
      entryPrice = bars[i].close;
    } else if (sig === "SELL" && inTrade) {
      const pct = (bars[i].close - entryPrice) / entryPrice;
      equity *= 1 + pct;
      inTrade = false;
      curve.push({ bar: i, equity });
    }
  }

  // Close any open position at last bar
  if (inTrade && bars.length > 0) {
    const lastClose = bars[bars.length - 1].close;
    const pct = (lastClose - entryPrice) / entryPrice;
    equity *= 1 + pct;
    curve.push({ bar: bars.length - 1, equity });
  }

  return curve;
}

// Performance metrics
interface PerfMetrics {
  totalReturn: number;
  totalSignals: number;
  buySignals: number;
  sellSignals: number;
  sharpeApprox: number;
}

function computeMetrics(
  bars: { close: number }[],
  signals: { bar: number; type: "BUY" | "SELL" }[],
): PerfMetrics {
  const buys = signals.filter((s) => s.type === "BUY").length;
  const sells = signals.filter((s) => s.type === "SELL").length;

  // Simple trade returns
  let inTrade = false;
  let entryPrice = 0;
  const tradeReturns: number[] = [];
  const signalMap = new Map(signals.map((s) => [s.bar, s.type]));

  for (let i = 1; i < bars.length; i++) {
    const sig = signalMap.get(i);
    if (sig === "BUY" && !inTrade) {
      inTrade = true;
      entryPrice = bars[i].close;
    } else if (sig === "SELL" && inTrade) {
      const ret = (bars[i].close - entryPrice) / entryPrice;
      tradeReturns.push(ret);
      inTrade = false;
    }
  }

  const totalReturn =
    tradeReturns.length > 0
      ? tradeReturns.reduce((acc, r) => acc * (1 + r), 1) - 1
      : 0;

  const mean =
    tradeReturns.length > 0
      ? tradeReturns.reduce((a, b) => a + b, 0) / tradeReturns.length
      : 0;
  const variance =
    tradeReturns.length > 1
      ? tradeReturns.reduce((a, r) => a + (r - mean) ** 2, 0) / tradeReturns.length
      : 0;
  const stdDev = Math.sqrt(variance);
  const sharpeApprox = stdDev > 0 ? (mean / stdDev) * Math.sqrt(tradeReturns.length) : 0;

  return {
    totalReturn,
    totalSignals: signals.length,
    buySignals: buys,
    sellSignals: sells,
    sharpeApprox,
  };
}

function PineTab() {
  // Pine editor state
  const [code, setCode] = useState(PINE_TEMPLATES.ema_crossover.code);
  const [symbol, setSymbol] = useState("NIFTY");
  const [exchange, setExchange] = useState("NSE_INDEX");
  const [interval, setInterval] = useState("1d");
  const [showTemplates, setShowTemplates] = useState(false);
  const [copied, setCopied] = useState(false);
  const [dateOpts] = useState<PineRunnerOptions>({});
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const { result, bars, isRunning, error, run, reset } = usePineRunner();

  const handleRun = () => {
    void run(code, symbol, exchange, interval, dateOpts);
  };

  const handleReset = () => {
    reset();
  };

  const handleCopyCode = () => {
    void navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  const handleTemplate = (key: string) => {
    const tmpl = PINE_TEMPLATES[key];
    if (tmpl) {
      setCode(tmpl.code);
      setShowTemplates(false);
      reset();
    }
  };

  const equityCurve = useMemo(
    () => (result && bars.length > 0 ? computeEquityCurve(bars, result.signals) : []),
    [result, bars],
  );

  const metrics = useMemo(
    () => (result && bars.length > 0 ? computeMetrics(bars, result.signals) : null),
    [result, bars],
  );

  const hasErrors = result && result.errors.length > 0;

  return (
    <div className="flex flex-col h-full gap-0 overflow-hidden">
      {/* Symbol / interval config bar */}
      <div className="flex items-center gap-2 px-3 pt-2 pb-1 flex-wrap shrink-0 border-b border-border-subtle">
        <Input
          className="w-24 h-7 text-xs bg-surface-base border-border-default text-text-primary font-mono"
          placeholder="NIFTY"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          aria-label="Symbol"
        />
        <Select value={exchange} onValueChange={setExchange}>
          <SelectTrigger className="w-28 h-7 text-xs bg-surface-base border-border-default text-text-primary" aria-label="Exchange">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-surface-card border-border-default text-text-primary">
            {EXCHANGES.map((ex) => (
              <SelectItem key={ex} value={ex} className="text-xs hover:bg-surface-elevated">{ex}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={interval} onValueChange={setInterval}>
          <SelectTrigger className="w-16 h-7 text-xs bg-surface-base border-border-default text-text-primary" aria-label="Interval">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-surface-card border-border-default text-text-primary">
            {INTERVALS.map((iv) => (
              <SelectItem key={iv} value={iv} className="text-xs hover:bg-surface-elevated">{iv}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="ml-auto flex items-center gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs border border-border-default text-text-muted hover:text-text-primary hover:bg-surface-elevated"
            onClick={handleCopyCode}
            title="Copy code"
            aria-label="Copy Pine Script code"
          >
            {copied ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs border border-border-default text-text-muted hover:text-text-primary hover:bg-surface-elevated"
            onClick={handleReset}
            title="Clear results"
            aria-label="Clear results"
          >
            <RotateCcw size={11} />
          </Button>
          <Button
            size="sm"
            className="h-7 text-xs bg-primary text-primary-foreground hover:bg-primary/90 font-medium px-3"
            onClick={handleRun}
            disabled={isRunning}
            aria-label="Run Pine Script backtest"
          >
            {isRunning ? (
              <span className="flex items-center gap-1.5">
                <span className="animate-spin inline-block w-2.5 h-2.5 border border-current border-t-transparent rounded-full" aria-hidden="true" />
                Running
              </span>
            ) : (
              <span className="flex items-center gap-1.5">
                <Play size={10} aria-hidden="true" />
                Run Backtest
              </span>
            )}
          </Button>
        </div>
      </div>

      {/* Template picker */}
      <div className="px-3 py-1 shrink-0 border-b border-border-subtle">
        <button
          className="flex items-center gap-1 text-xs text-text-muted hover:text-text-primary transition-colors"
          onClick={() => setShowTemplates((v) => !v)}
          aria-expanded={showTemplates}
          aria-controls="pine-templates"
        >
          <Code2 size={10} aria-hidden="true" />
          Templates
          {showTemplates ? <ChevronUp size={10} aria-hidden="true" /> : <ChevronDown size={10} aria-hidden="true" />}
        </button>
        {showTemplates && (
          <div id="pine-templates" className="flex flex-wrap gap-1 mt-1.5" role="list">
            {Object.entries(PINE_TEMPLATES).map(([key, tmpl]) => (
              <Button
                key={key}
                variant="ghost"
                size="sm"
                role="listitem"
                className="h-6 px-2 text-xs text-text-muted hover:text-text-primary hover:bg-surface-elevated border border-border-default"
                onClick={() => handleTemplate(key)}
                title={tmpl.description}
              >
                {tmpl.label}
              </Button>
            ))}
          </div>
        )}
      </div>

      {/* Code editor */}
      <div className="flex-1 min-h-0 flex flex-col">
        <textarea
          ref={textareaRef}
          className="flex-1 min-h-0 w-full resize-none bg-[#0d0d14] text-[#e2e8f0] font-mono text-xs p-3 leading-5 border-0 border-b border-border-subtle outline-none focus:ring-1 focus:ring-primary/30 placeholder:text-text-muted"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          spellCheck={false}
          aria-label="Pine Script editor"
          aria-multiline="true"
          role="textbox"
          style={{ tabSize: 4 }}
        />
      </div>

      {/* Results panel */}
      {(result || error) && (
        <div className="shrink-0 max-h-64 overflow-y-auto border-t border-border-default bg-surface-base">
          {/* Top-level API error */}
          {error && (
            <div className="flex items-start gap-2 px-3 py-2 text-xs text-red-400 bg-red-900/10 border-b border-border-subtle">
              <AlertCircle size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
              <span role="alert">{error}</span>
            </div>
          )}

          {/* Pine execution errors (non-fatal warnings) */}
          {hasErrors && (
            <div className="px-3 py-1.5 space-y-0.5 border-b border-border-subtle">
              {result.errors.map((err, i) => (
                <div key={i} className="flex items-start gap-1.5 text-xs text-yellow-400">
                  <AlertCircle size={10} className="mt-0.5 shrink-0" aria-hidden="true" />
                  <span>{err}</span>
                </div>
              ))}
            </div>
          )}

          {result && (
            <>
              {/* Performance metrics */}
              {metrics && (
                <div className="grid grid-cols-5 gap-px bg-border-subtle border-b border-border-default" role="region" aria-label="Performance metrics">
                  {[
                    {
                      label: "Total Return",
                      value: `${metrics.totalReturn >= 0 ? "+" : ""}${(metrics.totalReturn * 100).toFixed(2)}%`,
                      color: metrics.totalReturn >= 0 ? "text-emerald-400" : "text-red-400",
                    },
                    {
                      label: "Signals",
                      value: String(metrics.totalSignals),
                      color: "text-text-primary",
                    },
                    {
                      label: "Buy",
                      value: String(metrics.buySignals),
                      color: "text-emerald-400",
                    },
                    {
                      label: "Sell",
                      value: String(metrics.sellSignals),
                      color: "text-red-400",
                    },
                    {
                      label: "Sharpe~",
                      value: metrics.sharpeApprox.toFixed(2),
                      color: metrics.sharpeApprox >= 1 ? "text-emerald-400" : "text-text-secondary",
                    },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="bg-surface-card px-2 py-2">
                      <div className="text-xxs text-text-muted uppercase tracking-wider">{label}</div>
                      <div className={`text-sm font-mono font-bold tabular-nums ${color}`}>{value}</div>
                    </div>
                  ))}
                </div>
              )}

              {/* Equity curve — inline SVG sparkline */}
              {equityCurve.length >= 2 && (
                <div className="px-3 py-2 border-b border-border-subtle" role="img" aria-label="Equity curve chart">
                  <div className="text-xxs text-text-muted uppercase tracking-wider mb-1">Equity Curve</div>
                  <EquityCurveSparkline curve={equityCurve} />
                </div>
              )}

              {/* Plot legend */}
              {result.plots.length > 0 && (
                <div className="px-3 py-1.5 flex flex-wrap gap-2 border-b border-border-subtle" role="list" aria-label="Plot indicators">
                  {result.plots.map((plot) => (
                    <div key={plot.name} className="flex items-center gap-1" role="listitem">
                      <span
                        className="inline-block w-3 h-0.5 rounded-full"
                        style={{ backgroundColor: plot.color }}
                        aria-hidden="true"
                      />
                      <span className="text-xxs text-text-secondary">{plot.name}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Signals table */}
              {result.signals.length > 0 && (
                <div className="px-0">
                  <div className="text-xxs text-text-muted uppercase tracking-wider px-3 py-1">Signals ({result.signals.length})</div>
                  <div className="max-h-28 overflow-y-auto" role="region" aria-label="Trade signals">
                    <Table>
                      <TableHeader>
                        <TableRow className="border-border-subtle hover:bg-transparent">
                          <TableHead className="text-xxs text-text-muted h-6 pl-3 font-normal">Bar</TableHead>
                          <TableHead className="text-xxs text-text-muted h-6 font-normal">Date</TableHead>
                          <TableHead className="text-xxs text-text-muted h-6 font-normal">Signal</TableHead>
                          <TableHead className="text-xxs text-text-muted h-6 font-normal">Label</TableHead>
                          <TableHead className="text-xxs text-text-muted h-6 text-right pr-3 font-normal">Price</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {result.signals.slice(0, 50).map((sig, idx) => {
                          const bar = bars[sig.bar];
                          const dateStr = bar
                            ? new Date(bar.time * 1000).toLocaleDateString("en-IN", {
                                day: "2-digit",
                                month: "short",
                                year: "2-digit",
                              })
                            : "-";
                          return (
                            <TableRow key={idx} className="border-border-subtle hover:bg-surface-card">
                              <TableCell className="py-0.5 pl-3 text-xxs font-mono text-text-muted">{sig.bar}</TableCell>
                              <TableCell className="py-0.5 text-xxs text-text-secondary">{dateStr}</TableCell>
                              <TableCell className="py-0.5">
                                <Badge
                                  variant="outline"
                                  className={`text-xxs px-1 py-0 border-0 font-mono ${sig.type === "BUY" ? "bg-emerald-900/40 text-emerald-400" : "bg-red-900/40 text-red-400"}`}
                                >
                                  {sig.type}
                                </Badge>
                              </TableCell>
                              <TableCell className="py-0.5 text-xxs text-text-secondary">{sig.label}</TableCell>
                              <TableCell className="py-0.5 text-xxs font-mono text-right pr-3 text-text-primary">
                                {bar ? bar.close.toFixed(2) : "-"}
                              </TableCell>
                            </TableRow>
                          );
                        })}
                        {result.signals.length > 50 && (
                          <TableRow className="border-border-subtle">
                            <TableCell colSpan={5} className="py-1 pl-3 text-xxs text-text-muted">
                              ... and {result.signals.length - 50} more signals
                            </TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              )}

              {result.signals.length === 0 && !error && (
                <div className="px-3 py-3 text-xs text-text-muted">
                  No signals generated. Check your strategy logic or try a different date range / interval.
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// Equity curve sparkline rendered as an inline SVG — no charting library needed
function EquityCurveSparkline({ curve }: { curve: { bar: number; equity: number }[] }) {
  const W = 600;
  const H = 40;
  const pad = 2;

  const minE = Math.min(...curve.map((p) => p.equity));
  const maxE = Math.max(...curve.map((p) => p.equity));
  const rangeE = maxE - minE || 1;
  const minB = curve[0].bar;
  const maxB = curve[curve.length - 1].bar || 1;
  const rangeB = maxB - minB || 1;

  const toX = (b: number) => pad + ((b - minB) / rangeB) * (W - pad * 2);
  const toY = (e: number) => H - pad - ((e - minE) / rangeE) * (H - pad * 2);

  const pathD = curve
    .map((p, i) => `${i === 0 ? "M" : "L"}${toX(p.bar).toFixed(1)},${toY(p.equity).toFixed(1)}`)
    .join(" ");

  const finalEquity = curve[curve.length - 1].equity;
  const isPositive = finalEquity >= 10000;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full h-10"
      aria-hidden="true"
      preserveAspectRatio="none"
    >
      {/* Zero baseline at 10000 */}
      <line
        x1={pad}
        y1={toY(10000).toFixed(1)}
        x2={W - pad}
        y2={toY(10000).toFixed(1)}
        stroke="#2a2a3a"
        strokeWidth="0.5"
      />
      <path
        d={pathD}
        fill="none"
        stroke={isPositive ? "#22c55e" : "#ef4444"}
        strokeWidth="1.5"
      />
    </svg>
  );
}

// ---- Main component ----

export default function StrategyBuilderTool({ onClose }: Props) {
  const [legs, setLegs] = useState<Leg[]>([]);
  const [underlying, setUnderlying] = useState(UNDERLYINGS[0]);
  const [atm, setAtm] = useState(UNDERLYINGS[0].symbol === "NIFTY" ? 22500 : 48000);
  const [strikeGap, setStrikeGap] = useState(UNDERLYINGS[0].strikeGap);

  const netPremium = calculateNetPremium(legs);

  const handleUnderlyingChange = (symbol: string) => {
    const u = UNDERLYINGS.find((u) => u.symbol === symbol) ?? UNDERLYINGS[0];
    setUnderlying(u);
    setStrikeGap(u.strikeGap);
    setAtm(symbol === "BANKNIFTY" ? 48000 : symbol === "SENSEX" ? 80000 : symbol === "FINNIFTY" ? 22000 : 22500);
    setLegs([]);
  };

  const handleAdd = () => {
    setLegs((prev) => [
      ...prev,
      { id: genId(), action: "BUY", optionType: "CE", strike: atm, lots: 1, premium: 0 },
    ]);
  };

  const handleRemove = (id: string) => {
    setLegs((prev) => prev.filter((l) => l.id !== id));
  };

  const handleChange = (id: string, field: keyof Leg, value: unknown) => {
    setLegs((prev) => prev.map((l) => (l.id === id ? { ...l, [field]: value } : l)));
  };

  // Apply template — absorbed from OptionChainPicker's applyTemplate logic
  const handleTemplate = (key: string) => {
    const tmpl = STRATEGY_TEMPLATES[key];
    if (!tmpl) return;
    const newLegs: Leg[] = tmpl.legs.map((lt) => ({
      id: genId(),
      action: lt.action,
      optionType: lt.optionType,
      strike: atm + lt.strikeOffset * strikeGap,
      lots: lt.lots,
      premium: 0,
    }));
    setLegs(newLegs);
  };

  return (
    <div className="h-full flex flex-col bg-surface-base">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-default bg-surface-card shrink-0">
        <div className="flex items-center gap-2">
          <Brain size={16} className="text-primary" />
          <h1 className="font-heading font-bold text-lg text-text-primary">Strategy Builder</h1>
          <Badge variant="outline" className="text-xxs border-border-default text-text-muted font-normal">
            {underlying.symbol}
          </Badge>
          {legs.length > 0 && (
            <Badge
              variant="outline"
              className={`text-xxs px-1.5 border-0 font-mono ${netPremium <= 0 ? "bg-emerald-900/40 text-emerald-400" : "bg-red-900/40 text-red-400"}`}
            >
              {netPremium <= 0 ? "Credit" : "Debit"} {formatINR(Math.abs(netPremium))}
            </Badge>
          )}
        </div>
        <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors">
          <X size={15} />
        </button>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="legs" className="flex-1 flex flex-col min-h-0">
        <TabsList className="shrink-0 rounded-none bg-surface-base border-b border-border-default justify-start px-3 h-8 gap-1">
          <TabsTrigger value="legs" className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <Brain size={11} className="mr-1" aria-hidden="true" />Strategy Legs
          </TabsTrigger>
          <TabsTrigger value="payoff" className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <TrendingUp size={11} className="mr-1" aria-hidden="true" />Payoff
          </TabsTrigger>
          <TabsTrigger value="margin" className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <Zap size={11} className="mr-1" aria-hidden="true" />Margin
          </TabsTrigger>
          <TabsTrigger value="pine" className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <Code2 size={11} className="mr-1" aria-hidden="true" />Pine Script
          </TabsTrigger>
        </TabsList>

        <TabsContent value="legs" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <LegsTab
            legs={legs}
            onAdd={handleAdd}
            onRemove={handleRemove}
            onChange={handleChange}
            onTemplate={handleTemplate}
            atm={atm}
            onAtmChange={setAtm}
            underlying={underlying}
            onUnderlyingChange={handleUnderlyingChange}
            strikeGap={strikeGap}
            onStrikeGapChange={setStrikeGap}
          />
        </TabsContent>

        <TabsContent value="payoff" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <PayoffTab legs={legs} atm={atm} underlying={underlying} />
        </TabsContent>

        <TabsContent value="margin" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <MarginTab legs={legs} underlying={underlying} />
        </TabsContent>

        <TabsContent value="pine" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <PineTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
