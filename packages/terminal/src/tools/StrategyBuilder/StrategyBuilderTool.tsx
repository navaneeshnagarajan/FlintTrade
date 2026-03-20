// Absorbed patterns from:
//   openalgo-chart/src/components/OptionChainPicker/OptionChainPicker.jsx — multi-leg state, strategy templates, direction (buy/sell), net premium calc
//   openalgo-chart/src/services/strategyTemplates.js — STRATEGY_TEMPLATES, calculateNetPremium, validateStrategy, formatStrategyName

import { useState, useMemo } from "react";
import { Brain, X, Plus, Trash2, AlertCircle, TrendingUp, Zap } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

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
            <Brain size={11} className="mr-1" />Strategy Legs
          </TabsTrigger>
          <TabsTrigger value="payoff" className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <TrendingUp size={11} className="mr-1" />Payoff
          </TabsTrigger>
          <TabsTrigger value="margin" className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <Zap size={11} className="mr-1" />Margin
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
      </Tabs>
    </div>
  );
}
