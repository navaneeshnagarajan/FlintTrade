/**
 * LogTab — Trade Review's fills log.
 *
 * Thin wrapper around the canonical Fills surface (merge 2.11), date-ranged to
 * the tool's committed search window: the ranged FillsTable is journal-only
 * (the session tradebook is today-scoped), carries its own provenance guards
 * (Explore → badged sample fills; queries disabled), side filters, symbol
 * search, CSV export, stats footer and per-fill screenshot annotations — the
 * union that replaced the tool's old TradeLogTab and the TradeLog/TradeBook
 * widgets.
 *
 * This is the SINGLE import site for the Fills module inside the tool.
 * ORCHESTRATOR: if FillsTable moves (e.g. behind an index barrel), this import
 * is the one-line swap point.
 */

import { FillsTable } from "@/widgets/trading/Fills/FillsTable";

export interface LogTabProps {
  /** Committed inclusive IST range (``YYYY-MM-DD``) from the tool header. */
  startDate: string;
  endDate: string;
}

export function LogTab({ startDate, endDate }: LogTabProps) {
  return <FillsTable startDate={startDate} endDate={endDate} className="flex-1 min-h-0" />;
}
