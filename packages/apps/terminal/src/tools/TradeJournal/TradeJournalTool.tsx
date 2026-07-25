/**
 * Trade Review — the terminal's consolidated trade-analysis tool (merge 2.12).
 *
 * Formerly "Trade Journal". Tabs:
 *   - Log         — the canonical Fills table (merge 2.11), ranged to the
 *                   committed header window; replaced the old TradeLogTab.
 *   - Session     — today's session statistics (absorbed the SessionStats
 *                   widget: FIFO round trips via lib/pnl).
 *   - Performance — longer-horizon metrics with a Range/YTD scope toggle
 *                   (absorbed the TradePerformance widget and the old
 *                   Analytics tab; metrics via lib/journalAnalytics).
 *   - Calendar    — daily P&L heat calendar over real journalled trades
 *                   (absorbed the P&L Dashboard Calendar tab's data plane and
 *                   the HeatCalendar widget's rendering affordances).
 *   - Deep Analytics / Notes / Coach — unchanged.
 *
 * The tool id stays ``trade-journal`` (ToolsDropdown/TerminalRoute wiring is
 * shared surface); only the display identity is renamed.
 *
 * Adapted patterns from:
 *   trading-journal/frontend/app/dashboard/portfolios/[id]/page.tsx — TradesTable, win/loss stat cards
 *   trading-journal/frontend/app/dashboard/analytics/page.tsx — analytics metrics, formatINR pattern
 */

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BookOpen,
  X,
  Search,
  Calendar,
  Clock,
  FileText,
  Target,
  Trophy,
  AlertCircle,
  RefreshCw,
  Brain,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { getTradeJournal } from "@/services/ftApi";
import { useModeStore } from "@/stores/modeStore";
import { type Props } from "./types";
import { todayISO, sevenDaysAgoISO } from "./utils";
import { LogTab } from "./LogTab";
import { SessionTab } from "./SessionTab";
import { PerformanceTab } from "./PerformanceTab";
import { CalendarTab } from "./CalendarTab";
import { DeepAnalyticsTab } from "./DeepAnalyticsTab";
import { NotesTab } from "./NotesTab";
import { CoachTab } from "./CoachTab";
import { getSampleJournalTrades } from "./sampleJournal";

export default function TradeJournalTool({ onClose }: Props) {
  const isExploreMode = useModeStore((s) => s.mode === "explore");
  const [startDate, setStartDate] = useState(sevenDaysAgoISO);
  const [endDate, setEndDate] = useState(todayISO);
  const [strategy, setStrategy] = useState("");

  // Committed search state — only updates when user clicks Search
  const [queryStart, setQueryStart] = useState(sevenDaysAgoISO);
  const [queryEnd, setQueryEnd] = useState(todayISO);
  const [queryStrategy, setQueryStrategy] = useState("");

  const {
    data,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["tradeJournal", queryStart, queryEnd, queryStrategy],
    queryFn: () =>
      getTradeJournal(queryStart, queryEnd, queryStrategy || undefined, 200),
    enabled: !!queryStart && !isExploreMode,
  });

  const sampleTrades = useMemo(
    () =>
      isExploreMode
        ? getSampleJournalTrades(queryStart, queryEnd, queryStrategy, 200)
        : [],
    [isExploreMode, queryStart, queryEnd, queryStrategy],
  );
  const trades = isExploreMode ? sampleTrades : data?.trades ?? [];
  const effectiveIsLoading = isExploreMode ? false : isLoading;
  const effectiveIsError = isExploreMode ? false : isError;

  function handleSearch() {
    setQueryStart(startDate);
    setQueryEnd(endDate);
    setQueryStrategy(strategy);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") handleSearch();
  }

  return (
    <div className="h-full flex flex-col bg-surface-base">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border-default bg-surface-card shrink-0 flex-wrap">
        <div className="flex items-center gap-2 shrink-0">
          <BookOpen size={16} className="text-primary" />
          <h1 className="font-heading font-bold text-base text-text-primary">
            Trade Review
          </h1>
        </div>

        {/* Date range + strategy filters (the tool's timeframe selector) */}
        <div className="flex items-center gap-1.5 flex-1 min-w-0">
          <Input
            type="text"
            placeholder="YYYY-MM-DD"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            onKeyDown={handleKeyDown}
            className="h-7 text-xs w-28 bg-surface-base border-border-default text-text-primary placeholder:text-text-muted font-mono"
            aria-label="Start date"
          />
          <span className="text-text-muted text-xs shrink-0">to</span>
          <Input
            type="text"
            placeholder="YYYY-MM-DD"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            onKeyDown={handleKeyDown}
            className="h-7 text-xs w-28 bg-surface-base border-border-default text-text-primary placeholder:text-text-muted font-mono"
            aria-label="End date"
          />
          <Input
            type="text"
            placeholder="Strategy (optional)"
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            onKeyDown={handleKeyDown}
            className="h-7 text-xs w-36 bg-surface-base border-border-default text-text-primary placeholder:text-text-muted"
            aria-label="Strategy filter"
          />
          <Button
            size="sm"
            className="h-7 px-3 text-xs"
            onClick={handleSearch}
          >
            <Search size={11} className="mr-1" />
            Search
          </Button>
        </div>

        {/* Status badges */}
        <div className="flex items-center gap-2 shrink-0">
          {isExploreMode && !effectiveIsLoading && !effectiveIsError && (
            <Badge
              variant="outline"
              className="text-xxs border-amber-500/40 bg-amber-500/10 text-amber-300 font-normal"
            >
              Sample Data
            </Badge>
          )}
          {effectiveIsLoading && (
            <span className="text-xs text-text-muted flex items-center gap-1">
              <RefreshCw size={11} className="animate-spin" />
              Loading...
            </span>
          )}
          {effectiveIsError && (
            <span className="text-xs text-loss flex items-center gap-1">
              <AlertCircle size={11} />
              Error
              {/* The retry affordance lived in the old TradeLogTab; the shared
                  range query now retries from the header instead. */}
              <Button
                variant="ghost"
                size="sm"
                className="h-5 px-1.5 text-xxs text-text-muted hover:text-text-primary"
                onClick={() => refetch()}
              >
                Retry
              </Button>
            </span>
          )}
          {!effectiveIsLoading && !effectiveIsError && (
            <Badge
              variant="outline"
              className="text-xxs border-border-default text-text-muted font-normal"
            >
              {trades.length} trades
            </Badge>
          )}
          <Button variant="ghost" size="icon" onClick={onClose} className="h-6 w-6 text-text-muted hover:text-text-primary" aria-label="Close trade review">
            <X size={15} />
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="log" className="flex-1 flex flex-col min-h-0">
        <TabsList className="shrink-0 rounded-none bg-surface-base border-b border-border-default justify-start px-3 h-8 gap-1">
          <TabsTrigger
            value="log"
            className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted"
          >
            <BookOpen size={11} className="mr-1" />
            Log
          </TabsTrigger>
          <TabsTrigger
            value="session"
            className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted"
          >
            <Clock size={11} className="mr-1" />
            Session
          </TabsTrigger>
          <TabsTrigger
            value="performance"
            className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted"
          >
            <Trophy size={11} className="mr-1" />
            Performance
          </TabsTrigger>
          <TabsTrigger
            value="calendar"
            className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted"
          >
            <Calendar size={11} className="mr-1" />
            Calendar
          </TabsTrigger>
          <TabsTrigger
            value="deep-analytics"
            className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted"
          >
            <Target size={11} className="mr-1" />
            Deep Analytics
          </TabsTrigger>
          <TabsTrigger
            value="notes"
            className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted"
          >
            <FileText size={11} className="mr-1" />
            Notes
          </TabsTrigger>
          <TabsTrigger
            value="coach"
            className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted"
          >
            <Brain size={11} className="mr-1" />
            Coach
          </TabsTrigger>
        </TabsList>

        <TabsContent
          value="log"
          className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden"
        >
          <LogTab startDate={queryStart} endDate={queryEnd} />
        </TabsContent>

        <TabsContent
          value="session"
          className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden"
        >
          <SessionTab />
        </TabsContent>

        <TabsContent
          value="performance"
          className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden"
        >
          <PerformanceTab trades={trades} rangeLabel={`${queryStart} → ${queryEnd}`} />
        </TabsContent>

        <TabsContent
          value="calendar"
          className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden"
        >
          <CalendarTab />
        </TabsContent>

        <TabsContent
          value="deep-analytics"
          className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden"
        >
          <DeepAnalyticsTab trades={trades} />
        </TabsContent>

        <TabsContent
          value="notes"
          className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden"
        >
          <NotesTab />
        </TabsContent>

        <TabsContent
          value="coach"
          className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden"
        >
          <CoachTab trades={trades} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
