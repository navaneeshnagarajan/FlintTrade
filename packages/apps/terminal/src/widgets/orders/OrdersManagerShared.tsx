/**
 * OrdersManagerShared — common surface for the broker order-management
 * widgets (Forever/GTT, Super Orders, Conditional Triggers).
 *
 * Shares the honest-state primitives so every widget behaves identically:
 *   - LiveModeNotice: these are live-broker constructs; outside Live mode the
 *     widgets neither fetch nor pretend.
 *   - BrokerTargetSelect: broker/account selector fed by connected brokerStore
 *     accounts plus the OpenAlgo bridge default.
 *   - BrokerOrdersErrorNotice: surfaces backend refusals verbatim; a 501 maps
 *     to "Not available for this broker".
 *   - BrokerRowsTable: defensive table over adapter-specific rows (the
 *     backend forwards broker rows untouched, so fields are plucked from a
 *     candidate-key list and missing values render as an em dash — never
 *     fabricated).
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
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
import { findBrokerAccountMatch, useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { pickNativeBrokerOrderTargetFromState } from "@/services/brokerTargets";
import {
  isUnsupportedForBroker,
  type BrokerOrderRow,
  type BrokerTarget,
} from "@/lib/brokerOrdersApi";
import { useQuery } from "@tanstack/react-query";
import { getLotSize } from "@/services/ftApi";
import { DERIVATIVE_EXCHANGES, type LotSizeState } from "@/lib/orderGuards";

// ---------------------------------------------------------------------------
// Strict numeric parsers — one implementation in @/lib/orderGuards, shared
// with Smart Order (which carried its own byte-identical copy). Explicit zero
// stays zero, garbage is rejected — never parseInt-truncated.
// ---------------------------------------------------------------------------

export { parseWholeNumber, parsePriceValue } from "@/lib/orderGuards";

// ---------------------------------------------------------------------------
// Lot-size resolution for the broker-order widgets
// ---------------------------------------------------------------------------

/**
 * Resolve the contract lot size for a typed symbol, failing closed.
 *
 * Forever (GTT) and conditional-trigger orders both accept derivative
 * exchanges and both validated quantity with `parseWholeNumber` alone, so a
 * GTT sized in shares could rest against an NFO contract until it triggered.
 * They need the same `checkLotMultiple` treatment as the immediate order
 * paths, which needs a lot size to check against.
 *
 * Provenance is required to be positively live: the resolver route flags a
 * fallback-table hit with `is_sample_data`, and a guessed lot size is worse
 * than none because it validates a wrong quantity.
 *
 * @param symbol Raw symbol text as typed (trimmed and upper-cased here).
 * @param exchange Exchange code the order will be routed to.
 * @returns Lot state suitable for `checkLotMultiple` / `checkLotSizeVerified`.
 */
export function useResolvedLotSize(symbol: string, exchange: string): LotSizeState {
  const trimmed = symbol.trim().toUpperCase();
  const isDerivative = DERIVATIVE_EXCHANGES.has(exchange);
  const { data } = useQuery({
    queryKey: ["orders", "lot-size", trimmed, exchange],
    queryFn: () => getLotSize(trimmed, exchange),
    // Equities are not lot-multiplied, so there is nothing to resolve.
    enabled: isDerivative && trimmed.length > 0,
    staleTime: 60 * 60 * 1000,
    retry: false,
  });

  return useMemo(() => {
    if (!isDerivative) return { lotSize: null, verified: true };
    if (!data || data.lot_size <= 0 || data.is_sample_data !== false) {
      return { lotSize: null, verified: false };
    }
    return { lotSize: data.lot_size, verified: true };
  }, [data, isDerivative]);
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

type BrokerOrderAccount = ReturnType<typeof useBrokerStore.getState>["accounts"][number];

export function isBrokerOrderTargetableAccount(account: BrokerOrderAccount): boolean {
  return account.status === "connected" && account.read_only !== true;
}

export function brokerOrderTargetExists(
  target: Required<BrokerTarget>,
  accounts: ReturnType<typeof useBrokerStore.getState>["accounts"],
): boolean {
  if (encodeTarget(target) === encodeTarget(DEFAULT_BROKER_TARGET)) return true;
  return accounts.some(
    (account) =>
      isBrokerOrderTargetableAccount(account) &&
      account.broker === target.broker &&
      account.account_id === target.account_id,
  );
}

/**
 * Select the broker/account target for gated broker-management widgets.
 *
 * OpenAlgo remains primary when a bridge API key is present. In native-only
 * Live mode, the active connected native account becomes the initial target so
 * GTT/super/trigger/position writes do not silently hit OpenAlgo/default.
 */
export function useBrokerOrderTarget(
  mode: string,
): [Required<BrokerTarget>, (target: Required<BrokerTarget>) => void] {
  const apiKey = useConnectionStore((s) => s.apiKey);
  // Read the hydration gate reactively so the target recomputes once the raw
  // OpenAlgo apiKey is rehydrated after a reload. While un-hydrated the pure
  // selector fails closed (returns undefined), so this initial target falls
  // back to the default rather than diverting to a native account on a
  // transiently-empty apiKey.
  const openAlgoHydrated = useConnectionStore((s) => s.openAlgoHydrated);
  const { accounts, activeAccountId } = useBrokerStore(
    useShallow((s) => ({ accounts: s.accounts, activeAccountId: s.activeAccountId })),
  );

  const automaticTarget = useMemo<Required<BrokerTarget>>(
    () =>
      pickNativeBrokerOrderTargetFromState(mode, apiKey, accounts, activeAccountId, openAlgoHydrated) ??
      DEFAULT_BROKER_TARGET,
    [mode, apiKey, accounts, activeAccountId, openAlgoHydrated],
  );
  const [target, setTarget] = useState<Required<BrokerTarget>>(automaticTarget);
  const [manualTarget, setManualTarget] = useState(false);

  const chooseTarget = useCallback((next: Required<BrokerTarget>) => {
    setManualTarget(true);
    setTarget(next);
  }, []);

  useEffect(() => {
    const currentTargetGone = !brokerOrderTargetExists(target, accounts);
    if (!manualTarget || currentTargetGone) {
      setTarget((current) =>
        encodeTarget(current) === encodeTarget(automaticTarget) ? current : automaticTarget,
      );
      if (currentTargetGone) setManualTarget(false);
    }
  }, [accounts, automaticTarget, manualTarget, target]);

  return [target, chooseTarget];
}

/**
 * Select a connected native account from an explicit broker allow-list.
 *
 * Some management surfaces have no OpenAlgo equivalent and are implemented by
 * only a subset of native adapters. Returning `null` when none is connected
 * keeps their queries and write controls fail closed.
 */
export function useSupportedNativeBrokerOrderTarget(
  supportedBrokers: readonly string[],
): [Required<BrokerTarget> | null, (target: Required<BrokerTarget>) => void] {
  const { accounts, activeAccountId } = useBrokerStore(
    useShallow((s) => ({ accounts: s.accounts, activeAccountId: s.activeAccountId })),
  );
  const supportedKey = supportedBrokers.map((broker) => broker.toLowerCase()).sort().join("|");
  const candidates = useMemo(
    () =>
      accounts.filter(
        (account) =>
          account.source === "native" &&
          isBrokerOrderTargetableAccount(account) &&
          supportedKey.split("|").includes(account.broker.toLowerCase()),
      ),
    [accounts, supportedKey],
  );
  const automaticTarget = useMemo<Required<BrokerTarget> | null>(() => {
    const account =
      findBrokerAccountMatch(candidates, activeAccountId) ??
      candidates.find((candidate) => candidate.is_primary) ??
      candidates[0];
    return account
      ? { broker: account.broker, account_id: account.account_id }
      : null;
  }, [activeAccountId, candidates]);
  const [target, setTarget] = useState<Required<BrokerTarget> | null>(automaticTarget);
  const [manualTarget, setManualTarget] = useState(false);

  const chooseTarget = useCallback((next: Required<BrokerTarget>) => {
    setManualTarget(true);
    setTarget(next);
  }, []);

  useEffect(() => {
    const currentTargetExists =
      target !== null &&
      candidates.some(
        (account) =>
          account.broker === target.broker && account.account_id === target.account_id,
      );
    if (!manualTarget || !currentTargetExists) {
      setTarget((current) => {
        if (current === null || automaticTarget === null) {
          return current === automaticTarget ? current : automaticTarget;
        }
        return encodeTarget(current) === encodeTarget(automaticTarget)
          ? current
          : automaticTarget;
      });
      if (!currentTargetExists) setManualTarget(false);
    }
  }, [automaticTarget, candidates, manualTarget, target]);

  return [target, chooseTarget];
}

interface BrokerTargetSelectPolicy {
  includeOpenAlgo?: boolean;
  nativeOnly?: boolean;
  supportedBrokers?: readonly string[];
}

export function brokerOrderTargetOptions(
  accounts: BrokerOrderAccount[],
  policy: BrokerTargetSelectPolicy = {},
): { target: Required<BrokerTarget>; label: string }[] {
  const {
    includeOpenAlgo = true,
    nativeOnly = false,
    supportedBrokers,
  } = policy;
  const allowed = supportedBrokers?.map((broker) => broker.toLowerCase());
  const options: { target: Required<BrokerTarget>; label: string }[] = [];
  if (includeOpenAlgo) {
    options.push({ target: DEFAULT_BROKER_TARGET, label: "OpenAlgo · default" });
  }
  for (const account of accounts) {
    if (!isBrokerOrderTargetableAccount(account)) continue;
    if (nativeOnly && account.source !== "native") continue;
    if (allowed && !allowed.includes(account.broker.toLowerCase())) continue;
    const target = { broker: account.broker, account_id: account.account_id };
    if (options.some((option) => encodeTarget(option.target) === encodeTarget(target))) continue;
    options.push({
      target,
      label: `${account.broker.toUpperCase()} · ${account.label || account.account_id}`,
    });
  }
  return options;
}

export function BrokerTargetSelect({
  value,
  onChange,
  includeOpenAlgo = true,
  nativeOnly = false,
  supportedBrokers,
}: {
  value: Required<BrokerTarget> | null;
  onChange: (target: Required<BrokerTarget>) => void;
  includeOpenAlgo?: boolean;
  nativeOnly?: boolean;
  supportedBrokers?: readonly string[];
}) {
  const accounts = useBrokerStore(useShallow((s) => s.accounts));
  const options = brokerOrderTargetOptions(accounts, {
    includeOpenAlgo,
    nativeOnly,
    supportedBrokers,
  });

  return (
    <Select
      value={value === null ? undefined : encodeTarget(value)}
      onValueChange={(v) => onChange(decodeTarget(v))}
      disabled={options.length === 0}
    >
      <SelectTrigger className="h-7 w-44 text-xs" aria-label="Broker account">
        <SelectValue placeholder="No compatible account" />
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
