/**
 * PortfolioCard — Net worth + allocation bar (Equity/MF/Gold/F&O).
 */

import { BentoCard } from "@/components/bento/BentoCard";
import { useFunds } from "@/hooks/useFunds";
import { useHoldings } from "@/hooks/useHoldings";
import { usePositions } from "@/hooks/usePositions";
import { useAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import { getDemoFunds, getDemoHoldings } from "@/hooks/useModeData";
import {
  accountCharges,
  accountLedgerCash,
  accountNetWorth,
  accountNetWorthAccessibleName,
  formatAccountNetWorth,
  fundsFuturesMtmInLedger,
  netWorthApproximation,
  netWorthFigureTitle,
  positionsNetWorthContribution,
} from "@/lib/accountNetWorth";
import { useModeStore } from "@/stores/modeStore";
import { DemoBadge } from "./DemoBadge";
import { ExampleLabel } from "@/components/data/ExampleLabel";

interface AllocationSlice {
  label: string;
  color: string;
  pct: number;
}

const EXAMPLE_ALLOCATION: AllocationSlice[] = [
  { label: "Equity", color: "#3b82f6", pct: 45 },
  { label: "MF",     color: "#8b5cf6", pct: 30 },
  { label: "Gold",   color: "#f59e0b", pct: 10 },
  { label: "F&O",    color: "#22c55e", pct: 15 },
];

function formatSlicePct(pct: number): string {
  const rounded = Math.round(pct * 100) / 100;
  return `${Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2)}%`;
}

function realAllocation(equity: number, positions: number, cash: number): AllocationSlice[] {
  const parts = [
    { label: "Cash", color: "#34d399", value: cash },
    { label: "Positions", color: "#22c55e", value: positions },
    { label: "Equity", color: "#3b82f6", value: equity },
  ].filter((part) => part.value > 0);
  const total = parts.reduce((sum, part) => sum + part.value, 0);
  return parts.map((part) => ({
    label: part.label,
    color: part.color,
    pct: total > 0 ? (part.value / total) * 100 : 0,
  }));
}

export function PortfolioCard() {
  const mode = useModeStore((s) => s.mode);
  const isExplore = mode === "explore";
  const isPractice = mode === "practice";
  const accountReadsEnabled = useAccountReadsEnabled();
  const fundsQuery = useFunds({ enabled: accountReadsEnabled });
  const holdingsQuery = useHoldings({ enabled: accountReadsEnabled });
  const positionsQuery = usePositions({ enabled: accountReadsEnabled && !isExplore });

  const funds = isExplore ? getDemoFunds() : fundsQuery.data;
  const holdings = isExplore ? getDemoHoldings() : holdingsQuery.data;
  const bookReady = (query: { isSuccess: boolean; isError: boolean; isLoading: boolean }) =>
    query.isSuccess && !query.isError && !query.isLoading;
  // Same rule as Invest: a pending or failed position book is not an empty
  // one. Publishing early would show cash alone, then jump when the book lands.
  const expectsPositionBook = accountReadsEnabled && !isExplore;
  const positionBookReady = !expectsPositionBook || bookReady(positionsQuery);
  const positions = isExplore || !positionBookReady ? [] : (positionsQuery.data ?? []);
  // Example allocation stays until funds, holdings, and positions have all
  // loaded. Any one of them still loading or failed keeps the split provisional.
  const allocationIsAccount = !isExplore
    && bookReady(fundsQuery)
    && bookReady(holdingsQuery)
    && bookReady(positionsQuery);

  const equityValue = (holdings ?? []).reduce(
    (sum, holding) => sum + holding.ltp * Math.abs(holding.quantity),
    0,
  );
  const futuresMtmInLedger = fundsFuturesMtmInLedger(funds);
  const positionValue = positionsNetWorthContribution(positions, holdings ?? [], futuresMtmInLedger);
  const { approximate, missingAverageSymbols, openLegSymbols } = netWorthApproximation(
    positions,
    futuresMtmInLedger,
  );
  const showConnect = !isExplore && !accountReadsEnabled;
  const netWorthPublished = !showConnect && positionBookReady;
  const figureTitle = netWorthPublished
    ? netWorthFigureTitle(approximate, missingAverageSymbols, openLegSymbols)
    : undefined;
  const cash = accountLedgerCash(funds);
  const netWorth = accountNetWorth(
    holdings ?? [],
    cash,
    positions,
    accountCharges(isExplore ? getDemoFunds() : funds),
    futuresMtmInLedger,
  );
  const netWorthIsExample = isExplore && netWorth > 0;
  const allocation = allocationIsAccount
    ? realAllocation(equityValue, positionValue, cash)
    : EXAMPLE_ALLOCATION;

  return (
    <BentoCard size="default" label="Portfolio" data-testid="portfolio-card">
      {isExplore && <DemoBadge />}
      <div className="p-4 h-full flex flex-col gap-3">
        <p className="text-[10px] font-medium uppercase tracking-widest text-text-muted">
          {isExplore || accountReadsEnabled ? "Portfolio" : "Portfolio (Broker required)"}
        </p>

        <div>
          <p
            className="text-[10px] text-text-muted mb-0.5 flex items-center gap-1.5"
            title={figureTitle}
          >
            Net Worth
            {netWorthIsExample && <ExampleLabel testId="portfolio-net-worth-example" />}
          </p>
          <p
            className="font-mono text-xl font-semibold text-text-primary"
            data-testid="portfolio-net-worth"
            {...(figureTitle ? { title: figureTitle } : {})}
            {...(netWorthPublished ? { "data-value": netWorth } : {})}
            aria-label={netWorthPublished && approximate ? accountNetWorthAccessibleName(netWorth) : undefined}
          >
            {showConnect
              ? "Connect broker"
              : netWorthPublished
                ? formatAccountNetWorth(netWorth, approximate)
                : "—"}
          </p>
          {isPractice && netWorthPublished && (
            <p className="text-[10px] text-text-muted mt-0.5" data-testid="portfolio-charges-source">
              Practice account, after estimated charges
            </p>
          )}
        </div>

        <div>
          <p className="text-[10px] text-text-muted mb-1.5 flex items-center gap-1.5">
            Allocation
            {!allocationIsAccount && <ExampleLabel testId="allocation-example-label" />}
          </p>
          <div
            className="flex h-2 rounded-full overflow-hidden"
            role="img"
            aria-label="Portfolio allocation bar"
          >
            {allocation.map((slice) => (
              <div
                key={slice.label}
                style={{ width: `${slice.pct}%`, background: slice.color }}
                title={`${slice.label}: ${formatSlicePct(slice.pct)}`}
              />
            ))}
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2" data-testid="portfolio-allocation">
            {allocation.map((slice) => (
              <div key={slice.label} className="flex items-center gap-1">
                <span
                  className="inline-block w-2 h-2 rounded-full"
                  style={{ background: slice.color }}
                  aria-hidden="true"
                />
                <span className="text-[10px] text-text-secondary">
                  {slice.label} {formatSlicePct(slice.pct)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </BentoCard>
  );
}
