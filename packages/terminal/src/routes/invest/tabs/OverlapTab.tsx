/**
 * OverlapTab.tsx — Portfolio Overlap Detection for investors.
 *
 * Shows:
 *   - Which stocks appear in multiple holdings/funds (overlap detection)
 *   - Concentration risk: "Top 10 stocks = X% of your portfolio"
 *   - Sector concentration warnings (>30% in one sector flagged)
 *
 * Uses holdings from InvestContext. Seeded with sample data when no
 * broker is connected (20 holdings with deliberate overlaps).
 */

import { useMemo } from "react";
import {
  AlertTriangle,
  ShieldAlert,
  PieChart,
  BarChart3,
  Eye,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { classifySector } from "@/lib/sectors";
import { useInvest } from "../InvestContext";
import { formatINR, formatPercent } from "../formatters";
import type { Holding } from "@/types/api";

// ─── Sample holdings with deliberate overlaps ───────────────────────────────────

const SAMPLE_HOLDINGS: Holding[] = [
  // Reliance appears 3 times (simulating 3 different funds holding it)
  { symbol: "RELIANCE", exchange: "NSE", quantity: 50, averagePrice: 2450.00, ltp: 2945.00, pnl: 24750, pnlPercent: 20.2 },
  { symbol: "RELIANCE", exchange: "NSE", quantity: 30, averagePrice: 2680.00, ltp: 2945.00, pnl: 7950, pnlPercent: 9.9 },
  { symbol: "RELIANCE", exchange: "NSE", quantity: 20, averagePrice: 2800.00, ltp: 2945.00, pnl: 2900, pnlPercent: 5.2 },
  // HDFCBANK appears 3 times
  { symbol: "HDFCBANK", exchange: "NSE", quantity: 100, averagePrice: 1520.00, ltp: 1685.20, pnl: 16520, pnlPercent: 10.9 },
  { symbol: "HDFCBANK", exchange: "NSE", quantity: 60, averagePrice: 1600.00, ltp: 1685.20, pnl: 5112, pnlPercent: 5.3 },
  { symbol: "HDFCBANK", exchange: "NSE", quantity: 40, averagePrice: 1650.00, ltp: 1685.20, pnl: 1408, pnlPercent: 2.1 },
  // INFY appears 2 times
  { symbol: "INFY", exchange: "NSE", quantity: 80, averagePrice: 1650.00, ltp: 1842.00, pnl: 15360, pnlPercent: 11.6 },
  { symbol: "INFY", exchange: "NSE", quantity: 45, averagePrice: 1720.00, ltp: 1842.00, pnl: 5490, pnlPercent: 7.1 },
  // TCS appears 2 times
  { symbol: "TCS", exchange: "NSE", quantity: 25, averagePrice: 3800.00, ltp: 4120.00, pnl: 8000, pnlPercent: 8.4 },
  { symbol: "TCS", exchange: "NSE", quantity: 15, averagePrice: 3900.00, ltp: 4120.00, pnl: 3300, pnlPercent: 5.6 },
  // Single holdings (no overlap)
  { symbol: "ICICIBANK", exchange: "NSE", quantity: 120, averagePrice: 980.00, ltp: 1045.30, pnl: 7836, pnlPercent: 6.7 },
  { symbol: "SBIN", exchange: "NSE", quantity: 200, averagePrice: 720.00, ltp: 815.30, pnl: 19060, pnlPercent: 13.2 },
  { symbol: "TATAMOTORS", exchange: "NSE", quantity: 150, averagePrice: 850.00, ltp: 985.45, pnl: 20318, pnlPercent: 15.9 },
  { symbol: "ITC", exchange: "NSE", quantity: 300, averagePrice: 420.00, ltp: 465.80, pnl: 13740, pnlPercent: 10.9 },
  { symbol: "SUNPHARMA", exchange: "NSE", quantity: 40, averagePrice: 1480.00, ltp: 1625.30, pnl: 5812, pnlPercent: 9.8 },
  { symbol: "BAJFINANCE", exchange: "NSE", quantity: 20, averagePrice: 6800.00, ltp: 7245.00, pnl: 8900, pnlPercent: 6.5 },
  { symbol: "WIPRO", exchange: "NSE", quantity: 100, averagePrice: 480.00, ltp: 542.80, pnl: 6280, pnlPercent: 13.1 },
  { symbol: "BHARTIARTL", exchange: "NSE", quantity: 60, averagePrice: 1380.00, ltp: 1520.00, pnl: 8400, pnlPercent: 10.1 },
  { symbol: "MARUTI", exchange: "NSE", quantity: 10, averagePrice: 10200.00, ltp: 11450.00, pnl: 12500, pnlPercent: 12.3 },
  { symbol: "ADANIENT", exchange: "NSE", quantity: 35, averagePrice: 2600.00, ltp: 2840.00, pnl: 8400, pnlPercent: 9.2 },
];

// ─── Analysis functions (exported for testing) ──────────────────────────────────

export interface OverlapEntry {
  symbol: string;
  occurrences: number;
  totalQuantity: number;
  totalValue: number;
  portfolioPercent: number;
  sector: string;
}

export interface SectorConcentration {
  sector: string;
  value: number;
  percent: number;
  stockCount: number;
  isRisky: boolean;
}

export interface ConcentrationStats {
  top10Value: number;
  top10Percent: number;
  totalValue: number;
  uniqueStocks: number;
  totalHoldings: number;
}

export function computeOverlaps(holdings: Holding[]): OverlapEntry[] {
  const symbolMap = new Map<string, { qty: number; value: number; count: number }>();

  for (const h of holdings) {
    const key = h.symbol.toUpperCase();
    const current = symbolMap.get(key) ?? { qty: 0, value: 0, count: 0 };
    current.qty += h.quantity;
    current.value += h.ltp * h.quantity;
    current.count += 1;
    symbolMap.set(key, current);
  }

  const totalPortfolioValue = [...symbolMap.values()].reduce((sum, v) => sum + v.value, 0);

  return [...symbolMap.entries()]
    .filter(([, v]) => v.count > 1)
    .map(([symbol, v]) => ({
      symbol,
      occurrences: v.count,
      totalQuantity: v.qty,
      totalValue: v.value,
      portfolioPercent: totalPortfolioValue > 0 ? (v.value / totalPortfolioValue) * 100 : 0,
      sector: classifySector(symbol),
    }))
    .sort((a, b) => b.totalValue - a.totalValue);
}

export function computeSectorConcentration(holdings: Holding[]): SectorConcentration[] {
  const sectorMap = new Map<string, { value: number; stocks: Set<string> }>();

  for (const h of holdings) {
    const sector = classifySector(h.symbol);
    const current = sectorMap.get(sector) ?? { value: 0, stocks: new Set<string>() };
    current.value += h.ltp * h.quantity;
    current.stocks.add(h.symbol.toUpperCase());
    sectorMap.set(sector, current);
  }

  const totalValue = [...sectorMap.values()].reduce((sum, v) => sum + v.value, 0);

  return [...sectorMap.entries()]
    .map(([sector, v]) => {
      const percent = totalValue > 0 ? (v.value / totalValue) * 100 : 0;
      return {
        sector,
        value: v.value,
        percent,
        stockCount: v.stocks.size,
        isRisky: percent > 30,
      };
    })
    .sort((a, b) => b.percent - a.percent);
}

export function computeConcentrationStats(holdings: Holding[]): ConcentrationStats {
  // Aggregate by symbol
  const symbolMap = new Map<string, number>();
  for (const h of holdings) {
    const key = h.symbol.toUpperCase();
    symbolMap.set(key, (symbolMap.get(key) ?? 0) + h.ltp * h.quantity);
  }

  const values = [...symbolMap.values()].sort((a, b) => b - a);
  const totalValue = values.reduce((sum, v) => sum + v, 0);
  const top10Value = values.slice(0, 10).reduce((sum, v) => sum + v, 0);

  return {
    top10Value,
    top10Percent: totalValue > 0 ? (top10Value / totalValue) * 100 : 0,
    totalValue,
    uniqueStocks: symbolMap.size,
    totalHoldings: holdings.length,
  };
}

// ─── Sub-components ─────────────────────────────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  value,
  sublabel,
  variant = "default",
}: {
  icon: typeof PieChart;
  label: string;
  value: string;
  sublabel?: string;
  variant?: "default" | "warning" | "danger";
}) {
  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        variant === "default" && "bg-surface-card border-border-default",
        variant === "warning" && "bg-warning/5 border-warning/30",
        variant === "danger" && "bg-loss/5 border-loss/30",
      )}
    >
      <div className="flex items-center gap-2 mb-1">
        <Icon
          className={cn(
            "size-3.5",
            variant === "default" && "text-accent",
            variant === "warning" && "text-warning",
            variant === "danger" && "text-loss",
          )}
        />
        <span className="text-xxs text-text-muted uppercase tracking-wider">{label}</span>
      </div>
      <div className="text-sm font-semibold text-text-primary font-mono tabular-nums">{value}</div>
      {sublabel && <div className="text-xxs text-text-muted mt-0.5">{sublabel}</div>}
    </div>
  );
}

// ─── Main Component ─────────────────────────────────────────────────────────────

export function OverlapTab() {
  const { holdings: liveHoldings } = useInvest();

  // Use sample data when no live holdings available
  const holdings = liveHoldings.length > 0 ? liveHoldings : SAMPLE_HOLDINGS;
  const usingSample = liveHoldings.length === 0;

  const overlaps = useMemo(() => computeOverlaps(holdings), [holdings]);
  const sectors = useMemo(() => computeSectorConcentration(holdings), [holdings]);
  const stats = useMemo(() => computeConcentrationStats(holdings), [holdings]);

  const riskySectors = sectors.filter((s) => s.isRisky);

  return (
    <div className="space-y-6">
      {/* Sample data notice */}
      {usingSample && (
        <div className="flex items-center gap-2 px-3 py-2 bg-warning/5 border border-warning/20 rounded-lg">
          <Eye className="size-3.5 text-warning shrink-0" />
          <span className="text-xs text-warning">
            Showing sample portfolio with deliberate overlaps. Connect your broker to see real data.
          </span>
        </div>
      )}

      {/* Summary stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          icon={PieChart}
          label="Unique Stocks"
          value={String(stats.uniqueStocks)}
          sublabel={`${stats.totalHoldings} total holdings`}
        />
        <StatCard
          icon={BarChart3}
          label="Top 10 Concentration"
          value={formatPercent(stats.top10Percent)}
          sublabel={formatINR(stats.top10Value)}
          variant={stats.top10Percent > 80 ? "warning" : "default"}
        />
        <StatCard
          icon={AlertTriangle}
          label="Overlapping Stocks"
          value={String(overlaps.length)}
          sublabel={overlaps.length > 0 ? "Held in multiple entries" : "No overlaps detected"}
          variant={overlaps.length > 3 ? "warning" : "default"}
        />
        <StatCard
          icon={ShieldAlert}
          label="Sector Risk"
          value={riskySectors.length > 0 ? `${riskySectors.length} sector(s)` : "Balanced"}
          sublabel={riskySectors.length > 0 ? `>30% in ${riskySectors.map((s) => s.sector).join(", ")}` : "No sector exceeds 30%"}
          variant={riskySectors.length > 0 ? "danger" : "default"}
        />
      </div>

      {/* Overlap table */}
      {overlaps.length > 0 && (
        <div>
          <h2 className="text-sm font-heading font-semibold text-text-primary mb-2 flex items-center gap-2">
            <AlertTriangle className="size-4 text-warning" />
            Stock Overlaps
          </h2>
          <p className="text-xs text-text-muted mb-3">
            These stocks appear in multiple holdings. Consider consolidating for clearer tracking.
          </p>
          <div className="rounded-lg border border-border-default overflow-hidden">
            <Table aria-label="Stock overlaps">
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider">
                    Stock
                  </TableHead>
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-center">
                    Occurrences
                  </TableHead>
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">
                    Total Qty
                  </TableHead>
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">
                    Total Value
                  </TableHead>
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">
                    Portfolio %
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {overlaps.map((o) => (
                  <TableRow
                    key={o.symbol}
                    className="border-border-default hover:bg-surface-card transition-colors"
                  >
                    <TableCell className="py-2">
                      <div>
                        <div className="text-xs font-semibold text-text-primary font-mono">
                          {o.symbol}
                        </div>
                        <div className="text-xxs text-text-muted">{o.sector}</div>
                      </div>
                    </TableCell>
                    <TableCell className="py-2 text-center">
                      <Badge
                        variant="outline"
                        className="text-xxs h-5 font-mono text-warning border-warning/30 bg-warning/5"
                      >
                        {o.occurrences}x
                      </Badge>
                    </TableCell>
                    <TableCell className="py-2 text-right font-mono tabular-nums text-xs text-text-secondary">
                      {o.totalQuantity.toLocaleString("en-IN")}
                    </TableCell>
                    <TableCell className="py-2 text-right font-mono tabular-nums text-xs text-text-primary font-semibold">
                      {formatINR(o.totalValue)}
                    </TableCell>
                    <TableCell className="py-2 text-right">
                      <span
                        className={cn(
                          "font-mono tabular-nums text-xs font-semibold",
                          o.portfolioPercent > 15 ? "text-loss" : o.portfolioPercent > 10 ? "text-warning" : "text-text-secondary",
                        )}
                      >
                        {formatPercent(o.portfolioPercent)}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      {overlaps.length === 0 && (
        <div className="flex flex-col items-center justify-center py-8 gap-2 text-text-muted">
          <PieChart className="size-6 text-profit" />
          <span className="text-sm font-medium text-text-secondary">No overlaps detected</span>
          <span className="text-xs text-center max-w-sm">
            Your portfolio has no duplicate stock holdings. Well diversified.
          </span>
        </div>
      )}

      {/* Sector concentration */}
      <div>
        <h2 className="text-sm font-heading font-semibold text-text-primary mb-2 flex items-center gap-2">
          <PieChart className="size-4 text-accent" />
          Sector Concentration
        </h2>
        <p className="text-xs text-text-muted mb-3">
          Sectors above 30% allocation are flagged as concentration risk.
        </p>
        <div className="space-y-2">
          {sectors.map((s) => (
            <div
              key={s.sector}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-lg border",
                s.isRisky ? "bg-loss/5 border-loss/20" : "bg-surface-card border-border-default",
              )}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-text-primary">{s.sector}</span>
                  <span className="text-xxs text-text-muted">{s.stockCount} stock(s)</span>
                  {s.isRisky && (
                    <Badge variant="outline" className="text-xxs h-4 text-loss border-loss/30 bg-loss/5">
                      High
                    </Badge>
                  )}
                </div>
                {/* Progress bar */}
                <div className="mt-1.5 h-1.5 bg-surface-hover rounded-full overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full transition-[width]",
                      s.isRisky ? "bg-loss" : s.percent > 20 ? "bg-warning" : "bg-accent",
                    )}
                    style={{ width: `${Math.min(s.percent, 100)}%` }}
                  />
                </div>
              </div>
              <div className="text-right shrink-0">
                <div
                  className={cn(
                    "text-xs font-mono tabular-nums font-semibold",
                    s.isRisky ? "text-loss" : "text-text-primary",
                  )}
                >
                  {formatPercent(s.percent)}
                </div>
                <div className="text-xxs font-mono tabular-nums text-text-muted">
                  {formatINR(s.value)}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Concentration disclaimer */}
      <div className="flex items-start gap-2 px-3 py-2 bg-surface-card border border-border-default rounded-lg">
        <ShieldAlert className="size-3.5 text-text-muted shrink-0 mt-0.5" />
        <p className="text-xxs text-text-muted leading-relaxed">
          Overlap detection is based on symbol matching across your holdings. If you hold stocks
          through multiple funds or demat accounts, they will show as overlaps. This analysis does
          not constitute financial advice.
        </p>
      </div>
    </div>
  );
}
