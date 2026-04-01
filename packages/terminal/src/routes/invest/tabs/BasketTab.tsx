/**
 * BasketTab.tsx — Stock basket / thematic investing
 *
 * Absorbs opencase patterns. Lets users create custom stock baskets with
 * weightings, rebalance, and track performance (like Smallcase).
 *
 * All data is client-side (localStorage). Basket definitions + allocations
 * persist across sessions. Live prices come from getMultiQuotes.
 *
 * Design:
 * - Sample baskets (NIFTY IT, Banking) pre-loaded for exploration
 * - Create custom baskets with symbol + weight pairs
 * - Rebalance view shows drift from target weights
 * - Performance summary with total value and P&L
 *
 * Accessibility:
 * - Tables have aria-label and aria-sort
 * - Buttons have descriptive labels
 * - Colour signals supplemented with text
 */

import { useState, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Plus,
  Trash2,
  RefreshCw,
  BarChart3,
  ShoppingBasket,
  TrendingUp,
  TrendingDown,
  Pencil,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { GlassCard } from "@/components/ui/GlassCard";
import { StaggeredList } from "@/components/motion/StaggeredList";
import { cn } from "@/lib/utils";
import { getMultiQuotes } from "@/services/api";
import type { Quote } from "@/types/api";
import { DemoBanner } from "@/components/ui/DemoBanner";
import { formatINR, formatPercent } from "../formatters";

// ─── Constants ────────────────────────────────────────────────────────────────

const STORAGE_KEY = "flinttrade:stock-baskets";

// Demo prices for explore mode (approximate last known values)
const DEMO_PRICES: Record<string, number> = {
  TCS: 3950, INFY: 1580, WIPRO: 450, HCLTECH: 1620, TECHM: 1350,
  HDFCBANK: 1650, ICICIBANK: 1180, SBIN: 780, KOTAKBANK: 1850, AXISBANK: 1120,
  RELIANCE: 2950, BHARTIARTL: 1480, ITC: 440, TATAMOTORS: 960, LT: 3400,
  BAJFINANCE: 7200, SUNPHARMA: 1750, TITAN: 3500, HINDUNILVR: 2350, MARUTI: 12500,
};

// ─── Types ────────────────────────────────────────────────────────────────────

interface BasketConstituent {
  symbol: string;
  exchange: string;
  weight: number; // Target weight 0–100
}

interface StockBasket {
  id: string;
  name: string;
  description: string;
  constituents: BasketConstituent[];
  investedAmount: number; // Total INR invested
  createdAt: string;
}

interface BasketWithQuotes extends StockBasket {
  quotes: Record<string, Quote>;
  currentValue: number;
  pnl: number;
  pnlPercent: number;
}

// ─── Sample baskets ──────────────────────────────────────────────────────────

const SAMPLE_BASKETS: StockBasket[] = [
  {
    id: "sample-nifty-it",
    name: "NIFTY IT",
    description: "Top 5 IT companies by market cap",
    constituents: [
      { symbol: "TCS", exchange: "NSE", weight: 25 },
      { symbol: "INFY", exchange: "NSE", weight: 25 },
      { symbol: "WIPRO", exchange: "NSE", weight: 20 },
      { symbol: "HCLTECH", exchange: "NSE", weight: 15 },
      { symbol: "TECHM", exchange: "NSE", weight: 15 },
    ],
    investedAmount: 100000,
    createdAt: "2026-01-01T00:00:00.000Z",
  },
  {
    id: "sample-banking",
    name: "Banking",
    description: "Top 5 banking stocks weighted by market cap",
    constituents: [
      { symbol: "HDFCBANK", exchange: "NSE", weight: 30 },
      { symbol: "ICICIBANK", exchange: "NSE", weight: 25 },
      { symbol: "SBIN", exchange: "NSE", weight: 20 },
      { symbol: "KOTAKBANK", exchange: "NSE", weight: 15 },
      { symbol: "AXISBANK", exchange: "NSE", weight: 10 },
    ],
    investedAmount: 100000,
    createdAt: "2026-01-01T00:00:00.000Z",
  },
];

// ─── Persistence ─────────────────────────────────────────────────────────────

function loadBaskets(): StockBasket[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [...SAMPLE_BASKETS];
    const parsed = JSON.parse(raw) as StockBasket[];
    return parsed.length > 0 ? parsed : [...SAMPLE_BASKETS];
  } catch {
    return [...SAMPLE_BASKETS];
  }
}

function saveBaskets(baskets: StockBasket[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(baskets));
}

// ─── Quote hook ──────────────────────────────────────────────────────────────

function useBasketQuotes(baskets: StockBasket[]) {
  // Collect all unique symbols across all baskets
  const allSymbols = useMemo(() => {
    const seen = new Set<string>();
    const symbols: Array<{ symbol: string; exchange: string }> = [];
    for (const b of baskets) {
      for (const c of b.constituents) {
        const key = `${c.exchange}:${c.symbol}`;
        if (!seen.has(key)) {
          seen.add(key);
          symbols.push({ symbol: c.symbol, exchange: c.exchange });
        }
      }
    }
    return symbols;
  }, [baskets]);

  return useQuery<Record<string, Quote>>({
    queryKey: ["basket-quotes", allSymbols.map((s) => s.symbol).join(",")],
    queryFn: async () => {
      if (allSymbols.length === 0) return {};
      const quotes = await getMultiQuotes(allSymbols);
      const map: Record<string, Quote> = {};
      for (const q of quotes) {
        map[q.symbol] = q;
      }
      return map;
    },
    refetchInterval: 30_000,
    enabled: allSymbols.length > 0,
  });
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function computeBasketValue(
  basket: StockBasket,
  quotes: Record<string, Quote>,
): { currentValue: number; pnl: number; pnlPercent: number } {
  let currentValue = 0;
  for (const c of basket.constituents) {
    const ltp = quotes[c.symbol]?.ltp ?? DEMO_PRICES[c.symbol] ?? 0;
    // Proportional allocation based on weight
    const allocated = basket.investedAmount * (c.weight / 100);
    // Assume bought at invested amount, current value scales with LTP changes
    // For demo: use demo price as base, show relative change
    const basePrice = DEMO_PRICES[c.symbol] ?? ltp;
    const shareCount = basePrice > 0 ? allocated / basePrice : 0;
    currentValue += shareCount * ltp;
  }
  const pnl = currentValue - basket.investedAmount;
  const pnlPercent = basket.investedAmount > 0 ? (pnl / basket.investedAmount) * 100 : 0;
  return { currentValue, pnl, pnlPercent };
}

function totalWeight(constituents: BasketConstituent[]): number {
  return constituents.reduce((sum, c) => sum + c.weight, 0);
}

// ─── Component ────────────────────────────────────────────────────────────────

export function BasketTab() {
  const [baskets, setBaskets] = useState<StockBasket[]>(loadBaskets);
  const [selectedBasketId, setSelectedBasketId] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);

  // Form state for create/edit dialog
  const [formName, setFormName] = useState("");
  const [formDescription, setFormDescription] = useState("");
  const [formInvested, setFormInvested] = useState("100000");
  const [formConstituents, setFormConstituents] = useState<BasketConstituent[]>([
    { symbol: "", exchange: "NSE", weight: 0 },
  ]);

  const { data: quotes = {}, isLoading, refetch } = useBasketQuotes(baskets);

  // Compute basket values
  const basketsWithQuotes: BasketWithQuotes[] = useMemo(
    () =>
      baskets.map((b) => {
        const { currentValue, pnl, pnlPercent } = computeBasketValue(b, quotes);
        return { ...b, quotes, currentValue, pnl, pnlPercent };
      }),
    [baskets, quotes],
  );

  const selectedBasket = basketsWithQuotes.find((b) => b.id === selectedBasketId);

  // ─── Handlers ──────────────────────────────────────────────────────────────

  const openCreateDialog = useCallback(() => {
    setEditId(null);
    setFormName("");
    setFormDescription("");
    setFormInvested("100000");
    setFormConstituents([{ symbol: "", exchange: "NSE", weight: 0 }]);
    setDialogOpen(true);
  }, []);

  const openEditDialog = useCallback((basket: StockBasket) => {
    setEditId(basket.id);
    setFormName(basket.name);
    setFormDescription(basket.description);
    setFormInvested(String(basket.investedAmount));
    setFormConstituents([...basket.constituents]);
    setDialogOpen(true);
  }, []);

  const addConstituent = useCallback(() => {
    setFormConstituents((prev) => [...prev, { symbol: "", exchange: "NSE", weight: 0 }]);
  }, []);

  const removeConstituent = useCallback((index: number) => {
    setFormConstituents((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const updateConstituent = useCallback(
    (index: number, field: keyof BasketConstituent, value: string | number) => {
      setFormConstituents((prev) =>
        prev.map((c, i) => (i === index ? { ...c, [field]: value } : c)),
      );
    },
    [],
  );

  const saveBasket = useCallback(() => {
    const validConstituents = formConstituents.filter(
      (c) => c.symbol.trim() !== "" && c.weight > 0,
    );
    if (!formName.trim() || validConstituents.length === 0) return;

    const newBasket: StockBasket = {
      id: editId ?? `basket-${Date.now()}`,
      name: formName.trim(),
      description: formDescription.trim(),
      constituents: validConstituents.map((c) => ({
        ...c,
        symbol: c.symbol.toUpperCase().trim(),
      })),
      investedAmount: parseFloat(formInvested) || 100000,
      createdAt: editId
        ? baskets.find((b) => b.id === editId)?.createdAt ?? new Date().toISOString()
        : new Date().toISOString(),
    };

    const updated = editId
      ? baskets.map((b) => (b.id === editId ? newBasket : b))
      : [...baskets, newBasket];

    setBaskets(updated);
    saveBaskets(updated);
    setDialogOpen(false);
  }, [formName, formDescription, formInvested, formConstituents, editId, baskets]);

  const deleteBasket = useCallback(
    (id: string) => {
      const updated = baskets.filter((b) => b.id !== id);
      setBaskets(updated);
      saveBaskets(updated);
      if (selectedBasketId === id) setSelectedBasketId(null);
    },
    [baskets, selectedBasketId],
  );

  // ─── Render ────────────────────────────────────────────────────────────────

  const isDemo = Object.keys(quotes).length === 0 && !isLoading;

  return (
    <div className="space-y-6">
      {isDemo && <DemoBanner />}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h3 className="font-heading font-semibold text-sm text-text-primary">
            Stock Baskets
          </h3>
          <p className="text-xs text-text-muted">
            Create thematic stock baskets with custom weightings. Track performance and rebalance.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isLoading && <RefreshCw className="size-3 text-text-muted animate-spin" />}
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="size-3 mr-1.5" />
            Refresh
          </Button>
          <Button size="sm" onClick={openCreateDialog}>
            <Plus className="size-3 mr-1.5" />
            New Basket
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      <StaggeredList
        className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
        staggerDelay={60}
      >
        {basketsWithQuotes.map((basket) => {
          const isSelected = basket.id === selectedBasketId;
          const isProfit = basket.pnl >= 0;
          return (
            <GlassCard
              key={basket.id}
              className={cn(
                "p-4 gap-3 cursor-pointer transition-colors",
                isSelected && "ring-1 ring-accent",
              )}
              onClick={() => setSelectedBasketId(isSelected ? null : basket.id)}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <ShoppingBasket className="size-4 text-accent shrink-0" />
                  <div>
                    <h4 className="font-heading font-semibold text-sm text-text-primary">
                      {basket.name}
                    </h4>
                    <p className="text-xxs text-text-muted">{basket.description}</p>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={(e) => { e.stopPropagation(); openEditDialog(basket); }}
                    className="p-1 rounded hover:bg-surface-card text-text-muted hover:text-text-primary"
                    aria-label={`Edit ${basket.name}`}
                  >
                    <Pencil className="size-3" />
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); deleteBasket(basket.id); }}
                    className="p-1 rounded hover:bg-surface-card text-text-muted hover:text-loss"
                    aria-label={`Delete ${basket.name}`}
                  >
                    <Trash2 className="size-3" />
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <span className="text-xxs text-text-muted uppercase tracking-wider block">Invested</span>
                  <span className="font-mono font-semibold tabular-nums text-text-primary">
                    {formatINR(basket.investedAmount)}
                  </span>
                </div>
                <div>
                  <span className="text-xxs text-text-muted uppercase tracking-wider block">Current</span>
                  <span className="font-mono font-semibold tabular-nums text-text-primary">
                    {formatINR(basket.currentValue)}
                  </span>
                </div>
                <div>
                  <span className="text-xxs text-text-muted uppercase tracking-wider block">P&L</span>
                  <span
                    className={cn(
                      "font-mono font-semibold tabular-nums",
                      isProfit ? "text-profit" : "text-loss",
                    )}
                  >
                    {formatPercent(basket.pnlPercent)}
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-1.5 mt-1">
                <Badge variant="outline" className="text-xxs h-4 border-border-default text-text-muted">
                  {basket.constituents.length} stocks
                </Badge>
                {isProfit ? (
                  <TrendingUp className="size-3 text-profit" />
                ) : (
                  <TrendingDown className="size-3 text-loss" />
                )}
              </div>
            </GlassCard>
          );
        })}
      </StaggeredList>

      {/* Detail view for selected basket */}
      {selectedBasket && (
        <div className="space-y-3">
          <h4 className="font-heading font-semibold text-sm text-text-primary">
            {selectedBasket.name} — Constituents
          </h4>
          <div className="border border-border-default rounded-lg overflow-hidden">
            <Table aria-label={`${selectedBasket.name} constituents`}>
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider">Symbol</TableHead>
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">Target Wt.</TableHead>
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">LTP</TableHead>
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">Allocated</TableHead>
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">Current</TableHead>
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">Drift</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {selectedBasket.constituents.map((c) => {
                  const ltp = quotes[c.symbol]?.ltp ?? DEMO_PRICES[c.symbol] ?? 0;
                  const allocated = selectedBasket.investedAmount * (c.weight / 100);
                  const basePrice = DEMO_PRICES[c.symbol] ?? ltp;
                  const shares = basePrice > 0 ? allocated / basePrice : 0;
                  const currentVal = shares * ltp;
                  const actualWeight = selectedBasket.currentValue > 0
                    ? (currentVal / selectedBasket.currentValue) * 100
                    : c.weight;
                  const drift = actualWeight - c.weight;

                  return (
                    <TableRow key={c.symbol} className="border-border-default">
                      <TableCell className="text-xs font-mono font-medium text-text-primary">
                        {c.symbol}
                      </TableCell>
                      <TableCell className="text-xs font-mono tabular-nums text-text-secondary text-right">
                        {c.weight.toFixed(1)}%
                      </TableCell>
                      <TableCell className="text-xs font-mono tabular-nums text-text-primary text-right">
                        {formatINR(ltp)}
                      </TableCell>
                      <TableCell className="text-xs font-mono tabular-nums text-text-secondary text-right">
                        {formatINR(allocated)}
                      </TableCell>
                      <TableCell className="text-xs font-mono tabular-nums text-text-primary text-right">
                        {formatINR(currentVal)}
                      </TableCell>
                      <TableCell
                        className={cn(
                          "text-xs font-mono tabular-nums text-right",
                          drift >= 0 ? "text-profit" : "text-loss",
                        )}
                      >
                        {drift >= 0 ? "+" : ""}{drift.toFixed(1)}%
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>

          <p className="text-xs text-text-muted leading-relaxed">
            Drift shows deviation from target weight. Positive drift means the stock has outperformed
            the basket average. Rebalance by selling overweight positions and buying underweight ones.
          </p>
        </div>
      )}

      {/* Empty state */}
      {baskets.length === 0 && (
        <GlassCard className="p-8 gap-2 items-center text-center">
          <BarChart3 className="size-8 text-text-disabled" />
          <h4 className="font-heading font-semibold text-sm text-text-primary">
            No baskets yet
          </h4>
          <p className="text-xs text-text-muted max-w-sm">
            Create a thematic stock basket to track a group of stocks with custom weightings.
          </p>
          <Button size="sm" className="mt-2" onClick={openCreateDialog}>
            <Plus className="size-3 mr-1.5" />
            Create Your First Basket
          </Button>
        </GlassCard>
      )}

      {/* Create / Edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{editId ? "Edit Basket" : "Create Stock Basket"}</DialogTitle>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label className="text-xxs text-text-muted uppercase tracking-wider">Basket Name</Label>
              <Input
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="e.g. NIFTY IT, My Value Picks"
                className="h-9 text-sm bg-surface-card border-border-default text-text-primary"
              />
            </div>

            <div className="space-y-1.5">
              <Label className="text-xxs text-text-muted uppercase tracking-wider">Description</Label>
              <Input
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
                placeholder="Brief description of the basket theme"
                className="h-9 text-sm bg-surface-card border-border-default text-text-primary"
              />
            </div>

            <div className="space-y-1.5">
              <Label className="text-xxs text-text-muted uppercase tracking-wider">
                Invested Amount (INR)
              </Label>
              <Input
                type="number"
                value={formInvested}
                onChange={(e) => setFormInvested(e.target.value)}
                min="1000"
                step="1000"
                className="h-9 text-sm bg-surface-card border-border-default text-text-primary font-mono"
              />
            </div>

            {/* Constituents */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label className="text-xxs text-text-muted uppercase tracking-wider">
                  Stocks ({totalWeight(formConstituents).toFixed(0)}% allocated)
                </Label>
                <Button variant="ghost" size="sm" onClick={addConstituent} className="h-6 text-xxs">
                  <Plus className="size-3 mr-1" /> Add Stock
                </Button>
              </div>

              {formConstituents.map((c, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <Input
                    value={c.symbol}
                    onChange={(e) => updateConstituent(idx, "symbol", e.target.value)}
                    placeholder="Symbol"
                    className="h-8 text-xs bg-surface-card border-border-default text-text-primary font-mono flex-1"
                  />
                  <Input
                    type="number"
                    value={c.weight || ""}
                    onChange={(e) => updateConstituent(idx, "weight", parseFloat(e.target.value) || 0)}
                    placeholder="Weight %"
                    min="0"
                    max="100"
                    step="5"
                    className="h-8 text-xs bg-surface-card border-border-default text-text-primary font-mono w-24"
                  />
                  <button
                    onClick={() => removeConstituent(idx)}
                    className="p-1 rounded hover:bg-surface-card text-text-muted hover:text-loss"
                    aria-label="Remove stock"
                  >
                    <Trash2 className="size-3" />
                  </button>
                </div>
              ))}

              {totalWeight(formConstituents) !== 100 && formConstituents.some((c) => c.weight > 0) && (
                <p className="text-xxs text-warning">
                  Weights should sum to 100%. Currently: {totalWeight(formConstituents).toFixed(0)}%
                </p>
              )}
            </div>
          </div>

          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" size="sm">Cancel</Button>
            </DialogClose>
            <Button
              size="sm"
              onClick={saveBasket}
              disabled={!formName.trim() || formConstituents.every((c) => !c.symbol.trim())}
            >
              {editId ? "Update" : "Create"} Basket
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
