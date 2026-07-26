// LegsTab — leg builder for StrategyBuilder
// Extracted from StrategyBuilderTool.tsx
// Adapted patterns from openalgo-chart/src/components/OptionChainPicker/OptionChainPicker.jsx

import { Brain, Plus, Trash2, AlertCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { UNDERLYINGS } from "./types";
import { LOADABLE_STRATEGY_TEMPLATES } from "@/lib/strategyTemplates";
import { analyseVerticalSpread } from "@/lib/spreadAnalysis";
import { validateLegs, calculateNetPremium, formatINR } from "./utils";
import type { Leg, Direction, OptionType, Underlying } from "./types";

interface Props {
  legs: Leg[];
  onAdd: () => void;
  onRemove: (id: string) => void;
  onChange: (id: string, field: keyof Leg, value: unknown) => void;
  onTemplate: (key: string) => void;
  atm: number;
  onAtmChange: (v: number) => void;
  underlying: Underlying;
  onUnderlyingChange: (symbol: string) => void;
  strikeGap: number;
  onStrikeGapChange: (v: number) => void;
}

export function LegsTab({
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
}: Props) {
  const { valid, error } = validateLegs(legs);
  const netPremium = calculateNetPremium(legs);
  const isDebit = netPremium > 0;

  // Vertical-spread economics — carried over from the retired SpreadView
  // widget, which was the only surface in the terminal that checked them.
  // `validateLegs` above cannot tell a coherent vertical from an impossible
  // one (a debit larger than the strike width, a credit structure priced as a
  // debit); this can. Every other shape reports `not-a-vertical` and is left
  // alone.
  const spreadCheck = analyseVerticalSpread(legs, underlying.lotSize);

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
              <SelectItem key={u.symbol} value={u.symbol} className="text-xs hover:bg-surface-elevated">
                {u.symbol}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="flex items-center gap-1">
          <span className="text-xs text-text-muted" aria-hidden="true">ATM</span>
          <Input
            className="w-20 h-7 text-xs bg-surface-base border-border-default text-text-primary font-mono"
            type="number"
            value={atm}
            aria-label="At-the-money strike price"
            onChange={(e) => onAtmChange(Number(e.target.value))}
          />
        </div>

        <div className="flex items-center gap-1">
          <span className="text-xs text-text-muted" aria-hidden="true">Gap</span>
          <Input
            className="w-16 h-7 text-xs bg-surface-base border-border-default text-text-primary font-mono"
            type="number"
            value={strikeGap}
            aria-label="Strike gap"
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

      {/* Template quick-apply bar — the shared catalogue, filtered to the
          entries an options builder can actually represent (stock-leg and
          multi-expiry strategies stay reference-only in the widget). */}
      <div className="flex items-center gap-1 px-3 flex-wrap">
        {LOADABLE_STRATEGY_TEMPLATES.map((tmpl) => (
          <Button
            key={tmpl.id}
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xs text-text-muted hover:text-text-primary hover:bg-surface-elevated border border-border-default"
            onClick={() => onTemplate(tmpl.id)}
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
                        <SelectTrigger
                          className={`w-16 h-6 text-xs border-0 font-medium ${leg.action === "BUY" ? "bg-emerald-900/40 text-emerald-400" : "bg-red-900/40 text-red-400"}`}
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-surface-card border-border-default text-text-primary">
                          <SelectItem value="BUY"  className="text-xs hover:bg-surface-elevated text-emerald-400">BUY</SelectItem>
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

      {/* Vertical-spread economics */}
      {spreadCheck.kind === "invalid" && (
        <div
          role="alert"
          className="mx-3 flex items-start gap-1.5 rounded border border-red-500/30 bg-red-900/20 px-2 py-1.5 text-xs text-red-400"
        >
          <AlertCircle size={11} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>{spreadCheck.spread.label} spread: {spreadCheck.error}</span>
        </div>
      )}
      {spreadCheck.kind === "unpriced" && (
        <p className="px-3 text-xxs text-text-muted">
          {spreadCheck.spread.label} spread — enter the leg premiums to check its economics.
        </p>
      )}
      {spreadCheck.kind === "valid" && (
        <div className="mx-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xxs text-text-muted">
          <Badge variant="outline" className="text-xxs px-1.5 border-border-default text-text-secondary font-normal">
            {spreadCheck.spread.label} spread
          </Badge>
          <span>
            Max profit{" "}
            <span className="font-mono tabular-nums text-emerald-400">
              {formatINR(spreadCheck.metrics.maxProfit)}
            </span>
          </span>
          <span>
            Max loss{" "}
            <span className="font-mono tabular-nums text-red-400">
              {formatINR(spreadCheck.metrics.maxLoss)}
            </span>
          </span>
          <span>
            Breakeven{" "}
            <span className="font-mono tabular-nums text-text-primary">
              {spreadCheck.metrics.breakeven.toLocaleString("en-IN")}
            </span>
          </span>
        </div>
      )}

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
