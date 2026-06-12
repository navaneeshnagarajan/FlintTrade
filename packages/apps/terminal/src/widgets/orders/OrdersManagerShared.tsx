/**
 * OrdersManagerShared — common surface for the broker order-management
 * widgets (Forever/GTT, Super Orders, Conditional Triggers).
 *
 * Shares the honest-state primitives so every widget behaves identically:
 *   - LiveModeNotice: these are live-broker constructs; outside Live mode the
 *     widgets neither fetch nor pretend.
 *   - BrokerTargetSelect: broker/account selector fed by brokerStore gateway
 *     accounts plus the OpenAlgo bridge default — mirrors AccountSwitcher's
 *     data source.
 *   - BrokerOrdersErrorNotice: surfaces backend refusals verbatim; a 501 maps
 *     to "Not available for this broker".
 *   - BrokerRowsTable: defensive table over adapter-specific rows (the
 *     backend forwards broker rows untouched, so fields are plucked from a
 *     candidate-key list and missing values render as an em dash — never
 *     fabricated).
 */

import type { ReactNode } from "react";
import { useShallow } from "zustand/react/shallow";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useBrokerStore } from "@/stores/brokerStore";
import {
  isUnsupportedForBroker,
  type BrokerOrderRow,
  type BrokerTarget,
} from "@/lib/brokerOrdersApi";

// ---------------------------------------------------------------------------
// Strict numeric parsers (same contract as SmartOrderWidget's): explicit
// zero stays zero, garbage is rejected — never parseInt-truncated.
// ---------------------------------------------------------------------------

/** Parse a positive whole number ("1,000" → 1000); null for anything else. */
export function parseWholeNumber(raw: string): number | null {
  const digits = raw.trim().replace(/,/g, "");
  if (!/^\d+$/.test(digits)) return null;
  const value = Number.parseInt(digits, 10);
  return value > 0 ? value : null;
}

/** Parse a non-negative price ("123.45"); null for garbage or negatives. */
export function parsePriceValue(raw: string): number | null {
  const trimmed = raw.trim().replace(/,/g, "");
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return null;
  return Number.parseFloat(trimmed);
}

// ---------------------------------------------------------------------------
// Defensive row plucking — adapter rows are broker-specific
// ---------------------------------------------------------------------------

/** Return the first present, non-empty field among `keys`, else "—". */
export function pickField(row: BrokerOrderRow, keys: string[]): string {
  for (const key of keys) {
    const value = row[key];
    if (value === null || value === undefined) continue;
    if (typeof value === "string" && value.trim() === "") continue;
    if (typeof value === "object") continue;
    return String(value);
  }
  return "—";
}

/** Extract a row's order/alert id from a candidate-key list, else null. */
export function extractRowId(row: BrokerOrderRow, keys: string[]): string | null {
  const value = pickField(row, keys);
  return value === "—" ? null : value;
}

// ---------------------------------------------------------------------------
// Live-mode gating notice
// ---------------------------------------------------------------------------

export function LiveModeNotice({ feature }: { feature: string }) {
  return (
    <p className="text-xs text-warning bg-warning/10 border border-warning/30 rounded px-2.5 py-1.5">
      {feature} are live-broker constructs and serve Live mode only — switch to
      Live (and unlock with your PIN) to use this widget. Nothing is simulated
      here.
    </p>
  );
}

// ---------------------------------------------------------------------------
// Error surface — honest, with the 501 broker-capability mapping
// ---------------------------------------------------------------------------

export function brokerOrdersErrorMessage(error: unknown): string {
  if (isUnsupportedForBroker(error)) return "Not available for this broker.";
  if (error instanceof Error && error.message) return error.message;
  return "Request failed.";
}

export function BrokerOrdersErrorNotice({ error }: { error: unknown }) {
  if (error === null || error === undefined) return null;
  return (
    <p role="alert" className="text-xs text-loss bg-loss/10 border border-loss/20 rounded px-2.5 py-1.5">
      {brokerOrdersErrorMessage(error)}
    </p>
  );
}

// ---------------------------------------------------------------------------
// Broker/account target selector
// ---------------------------------------------------------------------------

const TARGET_SEPARATOR = "::";

function encodeTarget(target: Required<BrokerTarget>): string {
  return `${encodeURIComponent(target.broker)}${TARGET_SEPARATOR}${encodeURIComponent(target.account_id)}`;
}

function decodeTarget(value: string): Required<BrokerTarget> {
  const index = value.indexOf(TARGET_SEPARATOR);
  if (index < 0) return { broker: "openalgo", account_id: "default" };
  return {
    broker: decodeURIComponent(value.slice(0, index)),
    account_id: decodeURIComponent(value.slice(index + TARGET_SEPARATOR.length)),
  };
}

export const DEFAULT_BROKER_TARGET: Required<BrokerTarget> = {
  broker: "openalgo",
  account_id: "default",
};

export function BrokerTargetSelect({
  value,
  onChange,
}: {
  value: Required<BrokerTarget>;
  onChange: (target: Required<BrokerTarget>) => void;
}) {
  const accounts = useBrokerStore(useShallow((s) => s.accounts));

  const options: { target: Required<BrokerTarget>; label: string }[] = [
    { target: DEFAULT_BROKER_TARGET, label: "OpenAlgo · default" },
  ];
  for (const account of accounts) {
    const target = { broker: account.broker, account_id: account.account_id };
    if (options.some((o) => encodeTarget(o.target) === encodeTarget(target))) continue;
    options.push({
      target,
      label: `${account.broker.toUpperCase()} · ${account.label || account.account_id}`,
    });
  }

  return (
    <Select value={encodeTarget(value)} onValueChange={(v) => onChange(decodeTarget(v))}>
      <SelectTrigger className="h-7 w-44 text-xs" aria-label="Broker account">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem
            key={encodeTarget(option.target)}
            value={encodeTarget(option.target)}
            className="text-xs"
          >
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

// ---------------------------------------------------------------------------
// Generic rows table
// ---------------------------------------------------------------------------

export interface BrokerRowColumn {
  header: string;
  /** Candidate row keys, first present wins (adapter rows vary by broker). */
  keys: string[];
  align?: "left" | "right";
  mono?: boolean;
}

export function BrokerRowsTable({
  rows,
  columns,
  ariaLabel,
  rowKeyKeys,
  renderActions,
  emptyMessage,
}: {
  rows: BrokerOrderRow[];
  columns: BrokerRowColumn[];
  ariaLabel: string;
  /** Candidate keys for the React row key (falls back to the row index). */
  rowKeyKeys: string[];
  renderActions?: (row: BrokerOrderRow) => ReactNode;
  emptyMessage: string;
}) {
  if (rows.length === 0) {
    return <p className="text-xs text-text-muted px-1 py-2">{emptyMessage}</p>;
  }

  return (
    <div className="overflow-x-auto min-w-0">
      <Table aria-label={ariaLabel}>
        <TableHeader className="sticky top-0 bg-surface-card z-10">
          <TableRow>
            {columns.map((column) => (
              <TableHead
                key={column.header}
                className={`text-xxs text-text-muted uppercase tracking-wider px-2 py-1 whitespace-nowrap ${
                  column.align === "right" ? "text-right" : ""
                }`}
              >
                {column.header}
              </TableHead>
            ))}
            {renderActions && (
              <TableHead className="text-xxs text-text-muted uppercase tracking-wider px-2 py-1">
                Actions
              </TableHead>
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow
              key={extractRowId(row, rowKeyKeys) ?? `row-${index}`}
              className="border-t border-border-subtle hover:bg-surface-hover/50"
            >
              {columns.map((column) => (
                <TableCell
                  key={column.header}
                  className={`px-2 py-1 whitespace-nowrap ${
                    column.align === "right" ? "text-right" : ""
                  } ${column.mono ? "font-mono tabular-nums" : ""}`}
                >
                  {pickField(row, column.keys)}
                </TableCell>
              ))}
              {renderActions && (
                <TableCell className="px-2 py-1 whitespace-nowrap">
                  {renderActions(row)}
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
