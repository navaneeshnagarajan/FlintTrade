/**
 * PositionsWidget — "Positions", the canonical position-book surface.
 *
 * THREE presentations of ONE position book, chosen by the workspace panel
 * parameter `params.view`:
 *   • "table" (default) — the sortable book with the gated write verbs
 *     (per-row square-off, per-row convert, book-level exit-all) and the Excel
 *     export.
 *   • "net"             — the retired Net Position widget: same-symbol rows
 *     netted, flat symbols dropped, collapsible grouping by underlying, totals
 *     footer.
 *   • "heat"            — the retired Position Heat Map widget: squarified
 *     treemap sized by exposure and coloured by P&L%, grouped by sector,
 *     exchange or flat, with click-to-open-a-chart.
 *
 * WHY THEY ARE ONE WIDGET. All three read the SAME `queryKeys.positions.list`
 * cache through `usePositions` — there was one position book behind three
 * renderings, and the three disagreed about it: exposure was computed three
 * ways and P&L two, so an operator with two of them open saw one account
 * described by two different numbers. Positions is the host because it is the
 * only one with write verbs, and a write must act on the row the operator can
 * see.
 *
 * ONE NORMALISATION, ONE SET OF NUMBERS. Every view renders from the
 * `PositionRow[]` produced by `positionBook.ts`: P&L is `lib/pnl.ts`'s
 * `positionMtm` (the repo-wide mark-to-market definition), exposure is
 * `|qty| × (ltp || entry)`, and the sector comes from `lib/sectors.ts` — not
 * from a widget-local map. The header's P&L figure is the whole book's, in
 * every view.
 *
 * FROM THE RETIRED DASHBOARD (ruling D5). The table view also carries the two
 * position-facing capabilities the Dashboard widget uniquely had: the per-row
 * P&L% column and the FlintSegmentTracker position-status strip. Both render
 * the kernel's numbers (`pnlPercent`, `mtm`) — the Dashboard recomputed them
 * locally from the raw broker fields.
 *
 * WRITES STAY ON THE TABLE. Square-off and convert act on a broker row, which
 * only the table view shows; a net row is an aggregate of rows and squaring one
 * off would mean inventing a multi-leg plan, which this widget does not do.
 * Exit-all is book-level and stays in the header for every view. Every write
 * still goes through the existing gated paths — no new order path is
 * introduced here.
 *
 * DATA HONESTY. Explore renders ONE sample book (`sampleBook.ts`) with no
 * per-widget Sample chip — the Mode honesty bar owns that line — and no write
 * control is reachable there. Practice square-off and exit-all place the
 * opposite order through the same place route as the Order Pad. Convert and
 * the live exit-all verb stay on a connected Live book. Practice reads the
 * sandbox; Live reads the broker. A stale feed says so, and a failed feed says
 * the figures are frozen and when.
 */

import { useMemo, useState, useCallback, useEffect, useRef, memo } from "react";
import {
  Clock,
  Layers,
  FileDown,
  LogOut,
  Repeat,
  SquareX,
  AlertTriangle,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { FlintSegmentTracker } from "@flinttrade/design-system";
import { downloadExcel } from "@/services/ftApi.data";
import { postWithMode } from "@/services/ftApi.helpers";
import { LayaAdmissionNotice } from "@/components/orders/LayaAdmissionNotice";
import { RestoredFillTag } from "@/components/orders/RestoredFillTag";
import { layaNoticeFromOrderError, type LayaAdmissionNotice as LayaNotice } from "@/lib/layaAdmission";
import { LAYA_EXIT_WHILE_DOWN } from "@/lib/operatorIncident";
import { placeOrder } from "@/services/api";
import { emitNotification } from "@/components/NotificationCentre/useNotificationFeed";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useAccountReadContext } from "@/hooks/useAccountReadsEnabled";
import type { AccountAuthorityIdentity } from "@/hooks/useDataScope";
import { brokerAccountKey, findBrokerAccountMatch, useBrokerStore } from "@/stores/brokerStore";
import {
  accountAuthorityMatches,
  captureAccountAuthority,
  resolveAccountQueryUi,
  runGuardedAccountRefetch,
  runWithMatchingAccountAuthority,
} from "@/lib/accountQueryState";
import { isMarketHours } from "@/lib/market";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { totalPositionMtm } from "@/lib/pnl";
import { cn } from "@/lib/utils";
import {
  type ColumnDef,
  flexRender,
  type SortingState,
  useTable,
} from "@tanstack/react-table";
import { sortedTableFeatures, type SortedTableFeatures } from "@/lib/tableFeatures";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useOrders } from "@/hooks/useOrders";
import { usePositions } from "@/hooks/usePositions";
import {
  exitAlreadyPendingMessage,
  orderRefusalMessage,
  EXIT_PENDING_TAG,
  UNEXPECTED_POSITION_TAG,
  contractHasOpenExit,
  positionContractKey,
  positionFlipMessage,
  reconcilePositionSigns,
  type ExitOrderFields,
} from "./positionReconcile";
import { useNarrowLayout } from "@/hooks/useNarrowLayout";
import { NarrowBookCards } from "@/components/books/NarrowBookCards";
import type { WidgetProps } from "@/types/widgets";
import {
  fmtPnl,
  fmtPnlPct,
  fmtPrice,
  fmtUpdatedAt,
  netPositions,
  normalisePositions,
  type PositionRow,
} from "./positionBook";
import { SAMPLE_POSITION_BOOK } from "./sampleBook";
import NetPositionView from "./NetPositionView";
import HeatMapView, {
  GROUP_LABELS,
  GROUP_MODES,
  resolveGroupMode,
  type GroupMode,
} from "./HeatMapView";

// ---------------------------------------------------------------------------
// Views + panel params
// ---------------------------------------------------------------------------

type ViewMode = "table" | "net" | "heat";

const VIEW_MODES: readonly ViewMode[] = ["table", "net", "heat"];

const VIEW_LABELS: Record<ViewMode, string> = {
  table: "Table",
  net: "Net",
  heat: "Heat",
};

function isViewMode(value: unknown): value is ViewMode {
  return typeof value === "string" && (VIEW_MODES as readonly string[]).includes(value);
}

/** Resolves the `params.view` panel parameter, defaulting to table. */
function resolveViewMode(value: unknown): ViewMode {
  return isViewMode(value) ? value : "table";
}

interface PositionsPanelParams {
  /** Initial view — how the two retired ids select their old presentation. */
  view?: string;
  /** Initial heat-map grouping. */
  group?: string;
}

/** Position products supported by the convert and square-off verbs. */
const PRODUCTS = ["MIS", "CNC", "NRML"] as const;

interface PositionActionIntent {
  position: PositionRow;
  identity: AccountAuthorityIdentity;
}

interface ExitAllActionIntent {
  identity: AccountAuthorityIdentity;
}

/**
 * Staleness threshold relative to the poll cadence (5s market / 60s off-hours).
 * A frozen P&L figure without a warning is worse than an error banner.
 */
function staleThresholdMs(): number {
  return isMarketHours() ? 30_000 : 150_000;
}

// ---------------------------------------------------------------------------
// Convert-position dialog (gated convert_position verb)
// ---------------------------------------------------------------------------

interface ConvertPositionDialogProps {
  position: PositionRow;
  openingIdentity: AccountAuthorityIdentity;
  canSubmit: boolean;
  isActionAllowed: () => boolean;
  getCurrentIdentity: () => AccountAuthorityIdentity;
  onClose: () => void;
  onConverted: (mutationIdentity: AccountAuthorityIdentity) => void;
}

function ConvertPositionDialog({
  position,
  openingIdentity,
  canSubmit,
  isActionAllowed,
  getCurrentIdentity,
  onClose,
  onConverted,
}: ConvertPositionDialogProps) {
  const [toProduct, setToProduct] = useState<string>(position.product === "MIS" ? "CNC" : "MIS");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleConvert = useCallback(async () => {
    if (!isActionAllowed()) return;
    const mutationIdentity = runWithMatchingAccountAuthority(
      openingIdentity,
      getCurrentIdentity,
      () => captureAccountAuthority(getCurrentIdentity()),
    );
    if (!mutationIdentity) return;
    setIsSubmitting(true);
    setErrorMsg(null);
    try {
      // The backend signs the req object through the gated convert_position
      // verb; the field superset covers each adapter's expected names
      // (from/to_product, old/new_product, position_type, transaction_type).
      await postWithMode("positions/convert", {
        broker: mutationIdentity.brokerType,
        account_id: mutationIdentity.accountId,
        req: {
          symbol: position.symbol,
          exchange: position.exchange,
          quantity: Math.abs(position.quantity),
          position_type: position.quantity >= 0 ? "LONG" : "SHORT",
          transaction_type: position.quantity >= 0 ? "BUY" : "SELL",
          product: position.product,
          from_product: position.product,
          old_product: position.product,
          to_product: toProduct,
          new_product: toProduct,
        },
      }, mutationIdentity.mode);
      if (
        !isActionAllowed()
        || !accountAuthorityMatches(mutationIdentity, getCurrentIdentity())
      ) return;
      emitNotification({
        category: "system",
        title: "Position conversion submitted",
        body: `${position.symbol}: ${position.product || "current product"} → ${toProduct}.`,
      });
      onConverted(mutationIdentity);
      onClose();
    } catch (err) {
      // Surface mode-guard 403s and broker rejections honestly — the backend
      // message tells the operator exactly what blocked the conversion.
      setErrorMsg(err instanceof Error ? err.message : "Position conversion failed.");
    } finally {
      setIsSubmitting(false);
    }
  }, [
    position,
    toProduct,
    openingIdentity,
    isActionAllowed,
    getCurrentIdentity,
    onClose,
    onConverted,
  ]);

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Convert position</DialogTitle>
          <DialogDescription>
            Change the product of {position.symbol} ({position.quantity >= 0 ? "long" : "short"}{" "}
            {Math.abs(position.quantity)}
            {position.product ? `, currently ${position.product}` : ""}). Converting a position
            changes its margin treatment with your broker.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="convert-to-product">Target product</Label>
          <Select value={toProduct} onValueChange={setToProduct}>
            <SelectTrigger id="convert-to-product" className="w-full">
              <SelectValue placeholder="Select product" />
            </SelectTrigger>
            <SelectContent>
              {PRODUCTS.filter((p) => p !== position.product).map((p) => (
                <SelectItem key={p} value={p}>
                  {p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {errorMsg && (
          <p className="text-xs text-loss" role="alert">
            {errorMsg}
          </p>
        )}
        {!canSubmit && (
          <p className="text-xs text-warning" role="alert">
            Position data is unavailable or frozen. Close this dialog and reconnect before retrying.
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleConvert()}
            disabled={isSubmitting || !toProduct || !canSubmit}
            aria-label={`Convert ${position.symbol} to ${toProduct}`}
          >
            {isSubmitting ? "Converting…" : "Convert"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Square-off dialog (per-position exit through the existing gated place path)
// ---------------------------------------------------------------------------

interface SquareOffDialogProps {
  position: PositionRow;
  openingIdentity: AccountAuthorityIdentity;
  canSubmit: boolean;
  /** Practice fills need a positive mark. Live market orders keep price 0. */
  practice: boolean;
  isActionAllowed: () => boolean;
  getCurrentIdentity: () => AccountAuthorityIdentity;
  onClose: () => void;
  onSquaredOff: (mutationIdentity: AccountAuthorityIdentity) => void;
}

function squareOffProduct(position: PositionRow): (typeof PRODUCTS)[number] | null {
  return (PRODUCTS as readonly string[]).includes(position.product)
    ? (position.product as (typeof PRODUCTS)[number])
    : null;
}

function squareOffMark(position: PositionRow, practice: boolean): number {
  if (!practice) return 0;
  if (position.ltp > 0) return position.ltp;
  if (position.averagePrice > 0) return position.averagePrice;
  return 0;
}

function SquareOffDialog({
  position,
  openingIdentity,
  canSubmit,
  practice,
  isActionAllowed,
  getCurrentIdentity,
  onClose,
  onSquaredOff,
}: SquareOffDialogProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [layaNotice, setLayaNotice] = useState<LayaNotice | null>(null);

  const exitAction: "BUY" | "SELL" = position.quantity > 0 ? "SELL" : "BUY";
  const exitQty = Math.abs(position.quantity);
  // The counter-order must carry the position's own product, or the broker
  // opens a fresh position in a different product instead of squaring off.
  const product = squareOffProduct(position);

  const handleSquareOff = useCallback(async () => {
    if (!product || !isActionAllowed()) return;
    const mutationIdentity = runWithMatchingAccountAuthority(
      openingIdentity,
      getCurrentIdentity,
      () => captureAccountAuthority(getCurrentIdentity()),
    );
    if (!mutationIdentity) return;
    setIsSubmitting(true);
    setErrorMsg(null);
    setLayaNotice(null);
    try {
      // Same place route as the Order Pad: Laya, then SafetySystem on Live
      // and the sandbox on Practice.
      await placeOrder({
        symbol: position.symbol,
        exchange: position.exchange,
        action: exitAction,
        product,
        orderType: "MARKET",
        quantity: exitQty,
        price: squareOffMark(position, practice),
        triggerPrice: 0,
        strategy: "FlintPositions",
      }, mutationIdentity, { exit: true });
      if (
        !isActionAllowed()
        || !accountAuthorityMatches(mutationIdentity, getCurrentIdentity())
      ) return;
      const exitWhileDown = useOperatorSignalStore.getState().decisionStatus !== "ready";
      emitNotification({
        category: "order",
        title: exitWhileDown ? LAYA_EXIT_WHILE_DOWN : "Square-off submitted",
        body: exitWhileDown
          ? LAYA_EXIT_WHILE_DOWN
          : `${exitAction} ${exitQty} ${position.symbol} at market.`,
      });
      onSquaredOff(mutationIdentity);
      onClose();
    } catch (err) {
      const notice = layaNoticeFromOrderError(err);
      if (notice) {
        setLayaNotice(notice);
        setErrorMsg(null);
      } else {
        // Surface mode-guard 403s and broker rejections honestly — the backend
        // message tells the operator exactly what blocked the square-off.
        setLayaNotice(null);
        setErrorMsg(err instanceof Error ? err.message : "Square-off failed.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }, [
    position,
    practice,
    product,
    exitAction,
    exitQty,
    openingIdentity,
    isActionAllowed,
    getCurrentIdentity,
    onClose,
    onSquaredOff,
  ]);

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Square off position?</DialogTitle>
          <DialogDescription>
            This places a {exitAction} market order for {exitQty} {position.symbol} (
            {position.exchange}
            {position.product ? `, ${position.product}` : ""}) to close your{" "}
            {position.quantity > 0 ? "long" : "short"} position. Fills in a fast market can land far
            from the last traded price, and the action cannot be undone.
          </DialogDescription>
        </DialogHeader>
        {!product && (
          <p className="text-xs text-loss" role="alert">
            Cannot square off: unrecognised product
            {position.product ? ` “${position.product}”` : ""} on this position. Close it from your
            broker terminal instead.
          </p>
        )}
        <LayaAdmissionNotice notice={layaNotice} />
        {errorMsg && (
          <p className="text-xs text-loss" role="alert">
            {errorMsg}
          </p>
        )}
        {!canSubmit && (
          <p className="text-xs text-warning" role="alert">
            Position data is unavailable or frozen. Close this dialog and reconnect before retrying.
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleSquareOff()}
            disabled={isSubmitting || !product || !canSubmit}
            aria-label={`Confirm square off ${position.symbol}`}
            className="bg-loss hover:bg-loss/90 text-white"
          >
            {isSubmitting ? "Squaring off…" : `${exitAction} ${exitQty} at market`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Exit-all dialog (gated exit_all_positions verb — typed confirmation)
// ---------------------------------------------------------------------------

interface ExitAllRowFailure {
  key: string;
  symbol: string;
  notice: LayaNotice | null;
  message: string;
}

interface ExitAllDialogProps {
  open: boolean;
  positions: PositionRow[];
  /** Practice squares off each open row through place. Live uses exit-all. */
  practice: boolean;
  openingIdentity: AccountAuthorityIdentity;
  canSubmit: boolean;
  isActionAllowed: () => boolean;
  getCurrentIdentity: () => AccountAuthorityIdentity;
  hasPendingExit: (position: PositionRow) => boolean;
  onOpenChange: (open: boolean) => void;
  onExited: (mutationIdentity: AccountAuthorityIdentity) => void;
}

function ExitAllDialog({
  open,
  positions,
  practice,
  openingIdentity,
  canSubmit,
  isActionAllowed,
  getCurrentIdentity,
  hasPendingExit,
  onOpenChange,
  onExited,
}: ExitAllDialogProps) {
  const [confirmText, setConfirmText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [rowFailures, setRowFailures] = useState<ExitAllRowFailure[]>([]);
  const [squaredOff, setSquaredOff] = useState<string[]>([]);
  const confirmed = confirmText.trim() === "EXIT";
  const openRows = positions.filter((row) => row.quantity !== 0);
  const positionCount = openRows.length;

  const close = useCallback(
    (next: boolean) => {
      if (!next) {
        setConfirmText("");
        setErrorMsg(null);
        setRowFailures([]);
        setSquaredOff([]);
      }
      onOpenChange(next);
    },
    [onOpenChange],
  );

  const handleExitAll = useCallback(async () => {
    if (!confirmed || !isActionAllowed()) return;
    const mutationIdentity = runWithMatchingAccountAuthority(
      openingIdentity,
      getCurrentIdentity,
      () => captureAccountAuthority(getCurrentIdentity()),
    );
    if (!mutationIdentity) return;
    setIsSubmitting(true);
    setErrorMsg(null);
    setRowFailures([]);
    setSquaredOff([]);
    try {
      if (practice) {
        const failures: ExitAllRowFailure[] = [];
        const done: string[] = [];
        for (const position of openRows) {
          const product = squareOffProduct(position);
          const label = position.symbol;
          if (hasPendingExit(position)) {
            failures.push({
              key: `${position.symbol}-${position.exchange}-${position.product}`,
              symbol: label,
              notice: null,
              message: exitAlreadyPendingMessage(label),
            });
            continue;
          }
          if (!product) {
            failures.push({
              key: `${position.symbol}-${position.exchange}-${position.product}`,
              symbol: label,
              notice: null,
              message: `Cannot square off: unrecognised product${
                position.product ? ` “${position.product}”` : ""
              }.`,
            });
            continue;
          }
          try {
            await placeOrder({
              symbol: position.symbol,
              exchange: position.exchange,
              action: position.quantity > 0 ? "SELL" : "BUY",
              product,
              orderType: "MARKET",
              quantity: Math.abs(position.quantity),
              price: squareOffMark(position, true),
              triggerPrice: 0,
              strategy: "FlintPositions",
            }, mutationIdentity, { exit: true });
            done.push(label);
          } catch (err) {
            const notice = layaNoticeFromOrderError(err);
            failures.push({
              key: `${position.symbol}-${position.exchange}-${position.product}`,
              symbol: label,
              notice,
              message: notice
                ? ""
                : (err instanceof Error ? err.message : "Square-off failed."),
            });
          }
        }
        if (
          !isActionAllowed()
          || !accountAuthorityMatches(mutationIdentity, getCurrentIdentity())
        ) return;
        if (done.length > 0) onExited(mutationIdentity);
        if (failures.length > 0) {
          setSquaredOff(done);
          setRowFailures(failures);
          return;
        }
        const exitWhileDown = useOperatorSignalStore.getState().decisionStatus !== "ready";
        emitNotification({
          category: "system",
          title: exitWhileDown ? LAYA_EXIT_WHILE_DOWN : "Exit-all submitted",
          body: exitWhileDown
            ? LAYA_EXIT_WHILE_DOWN
            : "Every open Practice position was squared off at market.",
        });
        close(false);
        return;
      }
      if (openRows.some((position) => hasPendingExit(position))) {
        setErrorMsg(exitAlreadyPendingMessage(openRows.find((position) => hasPendingExit(position))?.symbol ?? ""));
        return;
      }
      await postWithMode("positions/exit-all", {
        confirm: true,
        broker: mutationIdentity.brokerType,
        account_id: mutationIdentity.accountId,
      }, mutationIdentity.mode);
      if (
        !isActionAllowed()
        || !accountAuthorityMatches(mutationIdentity, getCurrentIdentity())
      ) return;
      emitNotification({
        category: "system",
        title: "Exit-all submitted",
        body: "Every open position is being squared off at market.",
      });
      onExited(mutationIdentity);
      close(false);
    } catch (err) {
      // Mode-guard 403s ("live mode only", PIN unlock) and broker errors are
      // shown verbatim — never a generic failure.
      setErrorMsg(err instanceof Error ? err.message : "Exit-all positions failed.");
    } finally {
      setIsSubmitting(false);
    }
  }, [
    confirmed,
    openRows,
    practice,
    openingIdentity,
    isActionAllowed,
    getCurrentIdentity,
    onExited,
    close,
    hasPendingExit,
  ]);

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Exit all positions?</DialogTitle>
          <DialogDescription>
            {practice
              ? `This places an opposite market order for every open Practice position (${positionCount}). A refusal is shown on that row. Fills in a fast market can land far from the last traded price, and the action cannot be undone.`
              : `This squares off EVERY open position (${positionCount}) in your live broker account at market price. Fills in a fast market can land far from the last traded price, and the action cannot be undone.`}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="exit-all-confirm">Type EXIT (in capitals) to confirm</Label>
          <Input
            id="exit-all-confirm"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="EXIT"
            autoComplete="off"
          />
        </div>
        {squaredOff.length > 0 && (
          <p className="text-xs text-text-secondary" role="status">
            Squared off: {squaredOff.join(", ")}.
          </p>
        )}
        {rowFailures.map((failure) => (
          <div key={failure.key} className="space-y-0.5">
            <p className="text-xs font-medium text-text-primary">{failure.symbol}</p>
            {failure.notice ? (
              <LayaAdmissionNotice notice={failure.notice} />
            ) : (
              <p className="text-xs text-loss" role="alert">{failure.message}</p>
            )}
          </div>
        ))}
        {errorMsg && (
          <p className="text-xs text-loss" role="alert">
            {errorMsg}
          </p>
        )}
        {!canSubmit && (
          <p className="text-xs text-warning" role="alert">
            Position data is unavailable or frozen. Close this dialog and reconnect before retrying.
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleExitAll()}
            disabled={!confirmed || isSubmitting || !canSubmit}
            aria-label="Confirm exit all positions"
            className="bg-loss hover:bg-loss/90 text-white"
          >
            {isSubmitting ? "Exiting…" : "Exit all positions"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Host widget
// ---------------------------------------------------------------------------

const EMPTY_EXIT_ORDERS: ExitOrderFields[] = [];

function PositionsWidget(props: WidgetProps) {
  const panelParams = props.params as PositionsPanelParams | undefined;
  const [view, setView] = useState<ViewMode>(() => resolveViewMode(panelParams?.view));
  const [groupMode, setGroupMode] = useState<GroupMode>(() => resolveGroupMode(panelParams?.group));

  const track = useTrackBehavior();
  const accountReadContext = useAccountReadContext();
  const { identity: readIdentity, enabled: accountReadsEnabled } = accountReadContext;
  const appMode = readIdentity.mode;
  const isExplore = appMode === "explore";
  const {
    data: positionsData,
    dataUpdatedAt,
    isError,
    error,
    refetch,
    isFetching,
    isLoading,
    isSuccess,
    fetchStatus,
  } = usePositions({
    enabled: accountReadsEnabled,
    context: accountReadContext,
  });
  const { data: ordersData } = useOrders({
    enabled: accountReadsEnabled && !isExplore,
    context: accountReadContext,
  });
  const orders = ordersData ?? EMPTY_EXIT_ORDERS;

  const { isNarrow, containerRef } = useNarrowLayout<HTMLDivElement>();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [convertIntent, setConvertIntent] = useState<PositionActionIntent | null>(null);
  const [squareOffIntent, setSquareOffIntent] = useState<PositionActionIntent | null>(null);
  const [exitAllIntent, setExitAllIntent] = useState<ExitAllActionIntent | null>(null);
  const [unexpectedKeys, setUnexpectedKeys] = useState<ReadonlySet<string>>(() => new Set());
  const [flipToast, setFlipToast] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const heldSignsRef = useRef<Map<string, 1 | -1>>(new Map());
  const signsPrimedRef = useRef(false);
  const signsScopeRef = useRef(readIdentity.scopeKey);
  const brokerAccounts = useBrokerStore((state) => state.accounts);
  const activeAccountId = useBrokerStore((state) => state.activeAccountId);

  useEffect(() => {
    track("trade", `positions:view:${view}`);
  }, [track, view]);

  // ---- Data ---------------------------------------------------------------

  const rows = useMemo<PositionRow[]>(
    () => normalisePositions(isExplore ? SAMPLE_POSITION_BOOK : positionsData),
    [isExplore, positionsData],
  );
  const pendingExitKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const row of rows) {
      if (contractHasOpenExit(row, orders)) keys.add(positionContractKey(row));
    }
    return keys;
  }, [orders, rows]);

  useEffect(() => {
    if (isExplore) return;
    if (signsScopeRef.current !== readIdentity.scopeKey) {
      signsScopeRef.current = readIdentity.scopeKey;
      heldSignsRef.current = new Map();
      signsPrimedRef.current = false;
      setUnexpectedKeys(new Set());
      setFlipToast(null);
    }
    const reconciled = reconcilePositionSigns(heldSignsRef.current, rows);
    heldSignsRef.current = reconciled.next;
    if (!signsPrimedRef.current) {
      signsPrimedRef.current = true;
      return;
    }
    if (reconciled.flips.length === 0) return;
    setUnexpectedKeys((current) => {
      const merged = new Set(current);
      for (const flip of reconciled.flips) merged.add(flip.key);
      return merged;
    });
    const latest = reconciled.flips[reconciled.flips.length - 1];
    if (latest) {
      setFlipToast(positionFlipMessage(latest.side, latest.quantity, latest.symbol));
    }
  }, [isExplore, orders, readIdentity.scopeKey, rows]);
  const queryUi = resolveAccountQueryUi({
    accountReadsEnabled,
    fetchStatus,
    hasData: rows.length > 0,
    isError,
    isExplore,
    isLoading,
  });
  const activeAccount = useMemo(
    () => findBrokerAccountMatch(brokerAccounts, activeAccountId),
    [activeAccountId, brokerAccounts],
  );
  const exactActiveNativeBook = activeAccount?.source === "native"
    && activeAccount.status === "connected"
    && activeAccount.read_only !== true
    && readIdentity.brokerType === activeAccount.broker
    && readIdentity.accountId === activeAccount.account_id
    && readIdentity.scopeKey === `live:${brokerAccountKey(activeAccount)}`;
  const exactOpenAlgoBook = readIdentity.brokerType === "openalgo"
    && readIdentity.accountId === "default";
  const canMutateBook = appMode === "live" && queryUi.canRefetch && !isError;
  const practiceBookReady = appMode === "practice" && queryUi.canRefetch && !isError;
  const canSquareOff = practiceBookReady || (
    canMutateBook && (exactActiveNativeBook || exactOpenAlgoBook)
  );
  const canUseNativePositionVerbs = canMutateBook && exactActiveNativeBook;
  const canExitAll = practiceBookReady || canUseNativePositionVerbs;
  const nativeActionGateRef = useRef(canUseNativePositionVerbs);
  const squareOffActionGateRef = useRef(canSquareOff);
  const readIdentityRef = useRef(readIdentity);
  const refetchBoundaryRef = useRef({
    canRefetch: queryUi.canRefetch,
    identity: readIdentity,
    refetch,
  });
  nativeActionGateRef.current = canUseNativePositionVerbs;
  squareOffActionGateRef.current = canSquareOff;
  readIdentityRef.current = readIdentity;
  refetchBoundaryRef.current = {
    canRefetch: queryUi.canRefetch,
    identity: readIdentity,
    refetch,
  };

  const isNativeActionAllowed = useCallback(() => nativeActionGateRef.current, []);
  const isSquareOffAllowed = useCallback(() => squareOffActionGateRef.current, []);
  const getCurrentReadIdentity = useCallback(() => readIdentityRef.current, []);

  const convertCanSubmit = canUseNativePositionVerbs
    && convertIntent !== null
    && accountAuthorityMatches(convertIntent.identity, readIdentity);
  const squareOffCanSubmit = canSquareOff
    && squareOffIntent !== null
    && accountAuthorityMatches(squareOffIntent.identity, readIdentity);
  const exitAllCanSubmit = canExitAll
    && exitAllIntent !== null
    && accountAuthorityMatches(exitAllIntent.identity, readIdentity);

  useEffect(() => {
    if (convertIntent && (
      !canUseNativePositionVerbs
      || !accountAuthorityMatches(convertIntent.identity, readIdentity)
    )) {
      setConvertIntent(null);
    }
    if (squareOffIntent && (
      !canSquareOff
      || !accountAuthorityMatches(squareOffIntent.identity, readIdentity)
    )) {
      setSquareOffIntent(null);
    }
    if (exitAllIntent && (
      !canExitAll
      || !accountAuthorityMatches(exitAllIntent.identity, readIdentity)
    )) {
      setExitAllIntent(null);
    }
  }, [
    canExitAll,
    canSquareOff,
    canUseNativePositionVerbs,
    convertIntent,
    exitAllIntent,
    readIdentity,
    squareOffIntent,
  ]);

  const refreshPositions = useCallback((
    expectedIdentity: AccountAuthorityIdentity,
    getCurrentIdentity: () => AccountAuthorityIdentity,
  ) => {
    const boundary = refetchBoundaryRef.current;
    if (
      boundary.identity.mode !== expectedIdentity.mode
      || boundary.identity.scopeKey !== expectedIdentity.scopeKey
    ) return;
    runWithMatchingAccountAuthority(
      expectedIdentity,
      getCurrentIdentity,
      () => runGuardedAccountRefetch(boundary.canRefetch, boundary.refetch),
    );
  }, []);

  const netRows = useMemo(() => netPositions(rows), [rows]);
  const heatRows = useMemo(() => rows.filter((row) => row.exposure > 0), [rows]);

  /** Whole-book mark-to-market — the one P&L figure, shown in every view. */
  const totalPnl = useMemo(() => totalPositionMtm(rows), [rows]);
  const showPnl =
    isExplore || rows.length > 0 || (accountReadsEnabled && !queryUi.isPaused && isSuccess);
  const netExposure = useMemo(
    () => netRows.reduce((sum, row) => sum + row.exposure, 0),
    [netRows],
  );
  /** Broker rows the net view drops because their symbol nets flat. */
  const flatLegs = rows.length - netRows.reduce((sum, row) => sum + row.legs, 0);

  const visibleCount =
    view === "net" ? netRows.length : view === "heat" ? heatRows.length : rows.length;

  // ---- Staleness ----------------------------------------------------------

  // Ticks every 10s so the last-updated chip can flag staleness between polls.
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 10_000);
    return () => clearInterval(timer);
  }, []);

  const hasSuccessfulUpdate = dataUpdatedAt > 0;
  const hasUpdate = accountReadsEnabled && !queryUi.isFrozen && hasSuccessfulUpdate;
  const isStale = hasUpdate && nowMs - dataUpdatedAt > staleThresholdMs();

  // ---- Actions ------------------------------------------------------------

  const handleViewChange = useCallback(
    (next: ViewMode) => {
      if (next === view) return;
      setView(next);
      props.api.updateParameters({ view: next });
    },
    [props.api, view],
  );

  const handleGroupChange = useCallback(
    (next: GroupMode) => {
      setGroupMode(next);
      props.api.updateParameters({ group: next });
    },
    [props.api],
  );

  const handleExport = useCallback(async () => {
    if (rows.length === 0) return;
    setIsExporting(true);
    try {
      const count = await downloadExcel(
        rows.map((row) => ({
          symbol: row.symbol,
          exchange: row.exchange,
          product: row.product,
          quantity: row.quantity,
          avgPrice: row.averagePrice,
          ltp: row.ltp,
          pnl: row.mtm,
          exposure: row.exposure,
          sector: row.sector,
        })),
        "Positions",
        "positions.xlsx",
      );
      emitNotification({
        category: "system",
        title: "Positions exported",
        body: `Downloaded ${count} position${count === 1 ? "" : "s"} to positions.xlsx.`,
      });
    } catch (err) {
      emitNotification({
        category: "alert",
        title: "Export failed",
        body: err instanceof Error ? err.message : "Could not export positions to Excel.",
      });
    } finally {
      setIsExporting(false);
    }
  }, [rows]);

  const handleOpenChart = useCallback(
    (row: PositionRow) => {
      // Open a chart for the clicked position. Must dispatch `flinttrade:addWidget`
      // (handled in TerminalRoute) — the old `flinttrade:navigate` event carried no
      // `path`, so the AppLayout listener resolved null and the click was a no-op.
      track("trade", "positions:open-chart");
      window.dispatchEvent(
        new CustomEvent("flinttrade:addWidget", {
          detail: { widgetId: "chart", props: { symbol: row.symbol, exchange: row.exchange || "NSE" } },
        }),
      );
    },
    [track],
  );

  // ---- Table view ---------------------------------------------------------

  const closeReduced = useCallback(async (position: PositionRow) => {
    if (contractHasOpenExit(position, orders) || position.quantity === 0) return;
    const product = squareOffProduct(position);
    if (!product || !isSquareOffAllowed()) return;
    const identity = captureAccountAuthority(readIdentityRef.current);
    const exitAction = position.quantity > 0 ? "SELL" : "BUY";
    const exitQty = Math.abs(position.quantity);
    try {
      await placeOrder({
        symbol: position.symbol,
        exchange: position.exchange,
        action: exitAction,
        product,
        orderType: "MARKET",
        quantity: exitQty,
        price: squareOffMark(position, appMode === "practice"),
        triggerPrice: 0,
        strategy: "FlintPositions",
      }, identity, { exit: true });
      const exitWhileDown = useOperatorSignalStore.getState().decisionStatus !== "ready";
      emitNotification({
        category: "order",
        title: exitWhileDown ? LAYA_EXIT_WHILE_DOWN : "Square-off submitted",
        body: exitWhileDown
          ? LAYA_EXIT_WHILE_DOWN
          : `${exitAction} ${exitQty} ${position.symbol} at market.`,
      });
      refreshPositions(identity, getCurrentReadIdentity);
    } catch (err) {
      const code = err && typeof err === "object" && "body" in err
        && err.body && typeof err.body === "object" && "code" in err.body
        && typeof err.body.code === "string"
        ? err.body.code
        : undefined;
      emitNotification({
        category: "alert",
        title: "Close failed",
        body: orderRefusalMessage(
          code,
          position.symbol,
          err instanceof Error ? err.message : "Close failed.",
        ),
      });
    }
  }, [appMode, getCurrentReadIdentity, isSquareOffAllowed, orders, refreshPositions]);

  const renderRowActions = useCallback((position: PositionRow) => {
    const exitPending = pendingExitKeys.has(positionContractKey(position));
    const unexpected = unexpectedKeys.has(positionContractKey(position));
    if (!(canSquareOff || canUseNativePositionVerbs)) {
      // Explore has no book to trade. Practice with a frozen feed omits the hint.
      if (isExplore || appMode === "practice") return null;
      return <span className="text-xxs text-text-muted">Live only</span>;
    }
    return (
      <span className="inline-flex items-center gap-0.5">
        {canSquareOff && unexpected && position.quantity !== 0 && (
          <Button
            size="sm"
            variant="ghost"
            disabled={exitPending}
            onClick={() => {
              if (exitPending) return;
              void closeReduced(position);
            }}
            aria-label={`Close ${position.symbol}`}
            title={exitPending ? exitAlreadyPendingMessage(position.symbol) : `Close ${position.symbol} at market`}
            className="h-5 px-1.5 text-xxs gap-1 text-text-primary hover:bg-surface-hover"
          >
            Close
          </Button>
        )}
        {canSquareOff && position.quantity !== 0 && (
          <Button
            size="sm"
            variant="ghost"
            disabled={exitPending}
            onClick={() => {
              if (exitPending) return;
              setSquareOffIntent({
                position,
                identity: captureAccountAuthority(readIdentity),
              });
            }}
            aria-label={`Square off ${position.symbol}`}
            title={exitPending ? exitAlreadyPendingMessage(position.symbol) : `Square off ${position.symbol} at market`}
            className="h-5 px-1.5 text-xxs gap-1 text-loss hover:bg-loss/10 hover:text-loss"
          >
            <SquareX size={10} aria-hidden="true" /> Square off
          </Button>
        )}
        {canUseNativePositionVerbs && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setConvertIntent({
              position,
              identity: captureAccountAuthority(readIdentity),
            })}
            aria-label={`Convert ${position.symbol}`}
            title={`Convert ${position.symbol} to another product`}
            className="h-5 px-1.5 text-xxs gap-1 text-text-muted hover:text-text-primary"
          >
            <Repeat size={10} aria-hidden="true" /> Convert
          </Button>
        )}
      </span>
    );
  }, [
    appMode,
    canSquareOff,
    canUseNativePositionVerbs,
    closeReduced,
    isExplore,
    pendingExitKeys,
    readIdentity,
    unexpectedKeys,
  ]);

  const narrowCards = useMemo(
    () => rows.map((row) => ({
      id: `${row.symbol}-${row.exchange}-${row.product}-${
        row.quantity > 0 ? "long" : row.quantity < 0 ? "short" : "flat"
      }`,
      symbol: row.symbol,
      detail: `Qty ${row.quantity} · LTP ${fmtPrice(row.ltp)}`,
      pnl: fmtPnl(row.mtm),
      pnlPercent: fmtPnlPct(row.pnlPercent),
      pnlPositive: row.mtm >= 0,
      actions: renderRowActions(row),
    })),
    [renderRowActions, rows],
  );

  const columns = useMemo<ColumnDef<SortedTableFeatures, PositionRow>[]>(
    () => [
      {
        accessorKey: "symbol",
        header: "Symbol",
        cell: ({ row }) => {
          const key = positionContractKey(row.original);
          const exitPending = pendingExitKeys.has(key);
          const unexpected = unexpectedKeys.has(key);
          return (
            <span className="inline-flex items-center gap-1">
              <span className="font-mono font-medium">{row.original.symbol}</span>
              {exitPending ? (
                <span className="text-xxs text-warning">{EXIT_PENDING_TAG}</span>
              ) : null}
              {unexpected ? (
                <span className="text-xxs text-warning">{UNEXPECTED_POSITION_TAG}</span>
              ) : null}
              {row.original.restored ? <RestoredFillTag /> : null}
            </span>
          );
        },
      },
      {
        accessorKey: "quantity",
        header: "Qty",
        cell: ({ row }) => (
          <span
            className={`font-mono tabular-nums ${
              row.original.quantity > 0
                ? "text-profit"
                : row.original.quantity < 0
                  ? "text-loss"
                  : "text-text-secondary"
            }`}
          >
            {row.original.quantity}
          </span>
        ),
      },
      {
        accessorKey: "ltp",
        header: "LTP",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-text-secondary">
            {fmtPrice(row.original.ltp)}
          </span>
        ),
      },
      {
        accessorKey: "mtm",
        header: "P&L",
        cell: ({ row }) => (
          <span
            className={`font-mono tabular-nums font-medium ${
              row.original.mtm >= 0 ? "text-profit" : "text-loss"
            }`}
          >
            {fmtPnl(row.original.mtm)}
          </span>
        ),
      },
      {
        // Absorbed from the retired Dashboard widget's positions table. The
        // number is the kernel's `pnlPercent` (broker-supplied, else derived
        // once in `normalisePosition`), never a widget-local formula.
        accessorKey: "pnlPercent",
        header: "P&L%",
        cell: ({ row }) => (
          <span
            className={`font-mono tabular-nums ${
              row.original.pnlPercent >= 0 ? "text-profit" : "text-loss"
            }`}
          >
            {fmtPnlPct(row.original.pnlPercent)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "",
        enableSorting: false,
        cell: ({ row }) => renderRowActions(row.original),
      },
    ],
    [pendingExitKeys, renderRowActions, unexpectedKeys],
  );

  const table = useTable({
    features: sortedTableFeatures,
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
  });

  const emptyMessage = isExplore
    ? "No open positions"
    : queryUi.isPaused
      ? "Positions unavailable while offline"
      : accountReadsEnabled
        ? "No open positions"
        : "Connect a broker to load positions";
  const emptyHint =
    queryUi.canRefetch || isExplore
      ? "Open positions will appear here"
      : queryUi.isPaused
        ? "Reconnect to the internet to resume account reads"
        : "Live positions require a broker session";

  return (
    <div
      ref={containerRef}
      className="h-full flex flex-col overflow-hidden text-xs bg-surface-base"
      data-tour-target="positions"
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2 px-3 py-1.5 border-b border-border-default shrink-0 flex-wrap">
        <span className="text-xxs uppercase tracking-wider text-text-muted font-heading font-semibold">
          Positions{visibleCount > 0 ? ` (${visibleCount})` : ""}
        </span>
        <div className="flex items-center gap-2">
          {/* Provenance: what book is on screen. Separate from the capability
              chip below, which says what may be done to it. */}
          {appMode === "practice" && (
            <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
              Practice
            </span>
          )}
          {!isExplore && !accountReadsEnabled && (
            <span
              className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
              role="status"
              aria-label="Broker connection required for real positions"
            >
              Broker required
            </span>
          )}
          {accountReadsEnabled && appMode !== "live" && appMode !== "practice" && (
            <span
              className="px-1.5 py-0.5 text-xxs bg-surface-hover text-text-muted border border-border-subtle rounded"
              role="status"
              aria-label="Position management actions require Live mode"
            >
              Read-only
            </span>
          )}
          <span
            className={`font-mono tabular-nums font-medium ${
              showPnl ? (totalPnl >= 0 ? "text-profit" : "text-loss") : "text-text-muted"
            }`}
          >
            P&L: {showPnl ? fmtPnl(totalPnl) : "—"}
          </span>
          {hasUpdate && (
            <span
              className={cn(
                "text-xxs font-mono tabular-nums flex items-center gap-0.5",
                isStale ? "text-warning" : "text-text-muted",
              )}
              role="status"
              aria-label={`Positions last updated ${fmtUpdatedAt(dataUpdatedAt)}${isStale ? " — stale" : ""}`}
              title={
                isStale
                  ? "Position data has not refreshed recently — P&L may be stale."
                  : "Time of the last successful position refresh."
              }
            >
              <Clock size={8} aria-hidden="true" />
              {isStale ? "Stale since " : "Updated "}
              {fmtUpdatedAt(dataUpdatedAt)}
            </span>
          )}
          {/* View switcher — the three renderings of this one book. */}
          <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
            {VIEW_MODES.map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => handleViewChange(mode)}
                aria-pressed={mode === view}
                className={`px-2 py-0.5 text-xxs font-medium transition-colors ${
                  mode === view
                    ? "bg-accent/15 text-accent"
                    : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                }`}
              >
                {VIEW_LABELS[mode]}
              </button>
            ))}
          </div>
          {view === "heat" && (
            <Select value={groupMode} onValueChange={(v) => handleGroupChange(v as GroupMode)}>
              <SelectTrigger
                aria-label="Group heat map by"
                className="h-6 text-xxs bg-surface-hover border-border-subtle text-text-secondary focus:ring-accent/50 w-24"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-surface-card border-border-default">
                {GROUP_MODES.map((mode) => (
                  <SelectItem key={mode} value={mode} className="text-xxs text-text-primary focus:bg-surface-hover">
                    {GROUP_LABELS[mode]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {queryUi.canRefetch && !queryUi.isFrozen && rows.length > 0 && (
            <button
              type="button"
              onClick={() => void handleExport()}
              disabled={isExporting}
              aria-label="Export positions to Excel"
              title="Export positions to Excel"
              className="text-text-muted hover:text-text-primary transition-colors disabled:opacity-40"
            >
              <FileDown size={12} className={isExporting ? "animate-pulse" : ""} />
            </button>
          )}
          {canExitAll && rows.some((row) => row.quantity !== 0) && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setExitAllIntent({
                identity: captureAccountAuthority(readIdentity),
              })}
              aria-label="Exit all positions"
              title="Square off every open position at market"
              className="h-5 px-1.5 text-xxs gap-1 text-loss hover:bg-loss/10 hover:text-loss"
            >
              <LogOut size={10} aria-hidden="true" /> Exit all…
            </Button>
          )}
        </div>
      </div>

      {flipToast ? (
        <div
          role="status"
          data-testid="position-flip-toast"
          className="mx-3 mt-2 flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-text-primary"
        >
          <AlertTriangle size={12} className="mt-0.5 shrink-0 text-warning" aria-hidden="true" />
          <span className="flex-1">{flipToast}</span>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setFlipToast(null)}
            className="h-5 px-1.5 text-xxs"
          >
            Dismiss
          </Button>
        </div>
      ) : null}

      {/* Position-feed failure banner — retained rows remain visible and are
          explicitly frozen. Initial no-data failures never claim figures froze. */}
      {isError && !isExplore && (
        <div
          role="alert"
          className="flex items-center gap-2 px-3 py-2 mx-3 mt-2 bg-loss/10 border border-loss/20 rounded-md text-xs text-loss shrink-0"
        >
          <AlertTriangle size={12} className="shrink-0" aria-hidden="true" />
          <span className="flex-1">
            Failed to load positions
            {queryUi.isFrozen
              ? ` — displayed positions are frozen${
                  hasSuccessfulUpdate ? ` at ${fmtUpdatedAt(dataUpdatedAt)}` : ""
                }`
              : ""}
            {error instanceof Error && error.message ? `: ${error.message}` : "."}
          </span>
          <Button
            variant="link"
            size="sm"
            onClick={() => runGuardedAccountRefetch(queryUi.canRefetch, refetch)}
            disabled={!queryUi.canRefetch || isFetching}
            title="Retry the position fetch"
            className="shrink-0 h-auto p-0 text-xs font-medium text-loss hover:text-loss/80 disabled:opacity-50"
          >
            {isFetching ? "Retrying…" : "Retry"}
          </Button>
        </div>
      )}

      {queryUi.isFrozen && !isError && (
        <div
          role="status"
          className="px-3 py-1.5 mx-3 mt-2 bg-warning/10 border border-warning/20 rounded-md text-xs text-warning shrink-0"
        >
          {queryUi.isPaused
            ? "Offline — displayed positions are frozen"
            : "Broker disconnected — displayed positions are frozen"}
        </div>
      )}

      {/* Body — mutually exclusive: loading | empty | views | error-only */}
      {queryUi.showInitialLoading ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 size={16} className="animate-spin text-text-muted" aria-label="Loading positions" />
        </div>
      ) : rows.length === 0 && !isError ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-text-muted">
          <Layers size={24} className="text-text-disabled" />
          <span className="text-sm">{emptyMessage}</span>
        </div>
      ) : rows.length === 0 ? (
        // Failed first fetch with no retained rows: banner above is the body.
        null
      ) : view === "net" ? (
        <NetPositionView
          rows={netRows}
          totalPnl={totalPnl}
          totalExposure={netExposure}
          flatLegs={flatLegs}
        />
      ) : view === "heat" ? (
        <HeatMapView
          rows={heatRows}
          groupMode={groupMode}
          emptyMessage={emptyMessage}
          emptyHint={emptyHint}
          onOpenChart={handleOpenChart}
        />
      ) : (
        <div className="flex-1 flex flex-col min-h-0">
          {/* Position-status tracker — absorbed from the retired Dashboard
              widget. One segment per broker row, toned by the row's kernel
              mark-to-market (never the raw broker `pnl`, which is wrong for
              some brokers). Table view only: the net view has its own totals
              footer and the heat map IS a status visual. */}
          <div className="px-3 pt-2 shrink-0">
            <FlintSegmentTracker
              ariaLabel="Position status tracker"
              segments={rows.map((row) => ({
                key: `${row.symbol}-${row.exchange}-${row.product}`,
                label: `${row.symbol}: ${fmtPnl(row.mtm)}`,
                tone:
                  row.mtm > 0
                    ? ("profit" as const)
                    : row.mtm < 0
                      ? ("loss" as const)
                      : ("neutral" as const),
              }))}
            />
            <div className="flex gap-3 mt-1 text-xxs text-text-muted">
              <span className="text-profit">
                {rows.filter((row) => row.mtm > 0).length} profit
              </span>
              <span className="text-loss">
                {rows.filter((row) => row.mtm < 0).length} loss
              </span>
              <span>{rows.filter((row) => row.mtm === 0).length} flat</span>
            </div>
          </div>
          {isNarrow ? (
            <NarrowBookCards rows={narrowCards} ariaLabel="Positions" />
          ) : (
          <div className="flex-1 overflow-auto min-h-0">
          <div className="overflow-x-auto min-w-0">
          <Table>
            <TableHeader className="sticky top-0 bg-surface-card z-10">
              {table.getHeaderGroups().map((hg) => (
                <TableRow key={hg.id}>
                  {hg.headers.map((header) => (
                    <TableHead
                      key={header.id}
                      className={`text-xxs text-text-muted uppercase tracking-wider cursor-pointer select-none px-2 py-1 whitespace-nowrap ${
                        header.id !== "symbol" ? "text-right" : ""
                      }`}
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getIsSorted() === "asc"
                        ? " ↑"
                        : header.column.getIsSorted() === "desc"
                          ? " ↓"
                          : ""}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row, idx) => (
                <TableRow
                  key={`${row.original.symbol}-${row.original.exchange}-${row.original.product}-${
                    row.original.quantity > 0 ? "long" : row.original.quantity < 0 ? "short" : "flat"
                  }`}
                  className={`border-t border-border-subtle hover:bg-surface-hover/50 ${
                    idx % 2 === 1 ? "bg-surface-stripe" : ""
                  }`}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell
                      key={cell.id}
                      className={`px-2 py-1 whitespace-nowrap ${cell.column.id !== "symbol" ? "text-right" : ""}`}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          </div>
          </div>
          )}
        </div>
      )}


      {/* Convert-position dialog — keyed so state resets per position */}
      {convertIntent && (
        <ConvertPositionDialog
          key={`${convertIntent.position.symbol}-${convertIntent.position.exchange}-${convertIntent.position.product}`}
          position={convertIntent.position}
          openingIdentity={convertIntent.identity}
          canSubmit={convertCanSubmit}
          isActionAllowed={isNativeActionAllowed}
          getCurrentIdentity={getCurrentReadIdentity}
          onClose={() => setConvertIntent(null)}
          onConverted={(identity) => refreshPositions(identity, getCurrentReadIdentity)}
        />
      )}

      {/* Per-position square-off confirmation — keyed so state resets per position */}
      {squareOffIntent && (
        <SquareOffDialog
          key={`${squareOffIntent.position.symbol}-${squareOffIntent.position.exchange}-${squareOffIntent.position.product}-${squareOffIntent.position.quantity}`}
          position={squareOffIntent.position}
          openingIdentity={squareOffIntent.identity}
          canSubmit={squareOffCanSubmit}
          practice={appMode === "practice"}
          isActionAllowed={isSquareOffAllowed}
          getCurrentIdentity={getCurrentReadIdentity}
          onClose={() => setSquareOffIntent(null)}
          onSquaredOff={(identity) => refreshPositions(identity, getCurrentReadIdentity)}
        />
      )}

      {/* Exit-all typed-confirmation dialog */}
      {exitAllIntent && (
        <ExitAllDialog
          open
          positions={rows}
          practice={appMode === "practice"}
          openingIdentity={exitAllIntent.identity}
          canSubmit={exitAllCanSubmit}
          isActionAllowed={appMode === "practice" ? isSquareOffAllowed : isNativeActionAllowed}
          getCurrentIdentity={getCurrentReadIdentity}
          hasPendingExit={(position) => pendingExitKeys.has(positionContractKey(position))}
          onOpenChange={(open) => {
            if (!open) setExitAllIntent(null);
          }}
          onExited={(identity) => refreshPositions(identity, getCurrentReadIdentity)}
        />
      )}
    </div>
  );
}

export default memo(PositionsWidget);
