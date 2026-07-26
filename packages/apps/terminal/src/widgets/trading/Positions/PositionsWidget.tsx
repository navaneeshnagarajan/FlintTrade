/**
 * PositionsWidget — "Positions", the canonical position-book surface.
 *
 * THREE presentations of ONE position book, chosen by the Dockview panel
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
 * DATA HONESTY. Explore renders ONE labelled sample book (`sampleBook.ts`)
 * behind a "Sample" badge and a watermark, and no write control is reachable
 * there (they require Live plus a connected broker). Practice reads the
 * sandbox; Live reads the broker. A stale feed says so, and a failed feed says
 * the figures are frozen and when.
 */

import { useMemo, useState, useCallback, useEffect, memo } from "react";
import {
  Clock,
  Layers,
  FileDown,
  LogOut,
  Repeat,
  SquareX,
  AlertTriangle,
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
import { post } from "@/services/ftApi.helpers";
import { placeOrder } from "@/services/api";
import { emitNotification } from "@/components/NotificationCentre/useNotificationFeed";
import { BrokerTargetSelect, useBrokerOrderTarget } from "@/widgets/orders/OrdersManagerShared";
import { useModeStore } from "@/stores/modeStore";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { resolveAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import { isMarketHours } from "@/lib/market";
import { totalPositionMtm } from "@/lib/pnl";
import { cn } from "@/lib/utils";
import type { BrokerTarget } from "@/lib/brokerOrdersApi";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePositions } from "@/hooks/usePositions";
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

/** Resolves the Dockview `params.view` panel parameter, defaulting to table. */
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
  target: Required<BrokerTarget>;
  onClose: () => void;
  onConverted: () => void;
}

function ConvertPositionDialog({ position, target, onClose, onConverted }: ConvertPositionDialogProps) {
  const [toProduct, setToProduct] = useState<string>(position.product === "MIS" ? "CNC" : "MIS");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleConvert = useCallback(async () => {
    setIsSubmitting(true);
    setErrorMsg(null);
    try {
      // The backend signs the req object through the gated convert_position
      // verb; the field superset covers each adapter's expected names
      // (from/to_product, old/new_product, position_type, transaction_type).
      await post("positions/convert", {
        broker: target.broker,
        account_id: target.account_id,
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
      });
      emitNotification({
        category: "system",
        title: "Position conversion submitted",
        body: `${position.symbol}: ${position.product || "current product"} → ${toProduct}.`,
      });
      onConverted();
      onClose();
    } catch (err) {
      // Surface mode-guard 403s and broker rejections honestly — the backend
      // message tells the operator exactly what blocked the conversion.
      setErrorMsg(err instanceof Error ? err.message : "Position conversion failed.");
    } finally {
      setIsSubmitting(false);
    }
  }, [position, target, toProduct, onClose, onConverted]);

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
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleConvert()}
            disabled={isSubmitting || !toProduct}
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
  onClose: () => void;
  onSquaredOff: () => void;
}

function SquareOffDialog({ position, onClose, onSquaredOff }: SquareOffDialogProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const exitAction: "BUY" | "SELL" = position.quantity > 0 ? "SELL" : "BUY";
  const exitQty = Math.abs(position.quantity);
  // The counter-order must carry the position's own product, or the broker
  // opens a fresh position in a different product instead of squaring off.
  const product = (PRODUCTS as readonly string[]).includes(position.product)
    ? (position.product as (typeof PRODUCTS)[number])
    : null;

  const handleSquareOff = useCallback(async () => {
    if (!product) return;
    setIsSubmitting(true);
    setErrorMsg(null);
    try {
      // Existing gated order path: SafetySystem → gate_order → BrokerRouter.
      // Identical route to the Order Pad — no new order path is introduced.
      await placeOrder({
        symbol: position.symbol,
        exchange: position.exchange,
        action: exitAction,
        product,
        orderType: "MARKET",
        quantity: exitQty,
        price: 0,
        triggerPrice: 0,
        strategy: "FlintPositions",
      });
      emitNotification({
        category: "order",
        title: "Square-off submitted",
        body: `${exitAction} ${exitQty} ${position.symbol} at market.`,
      });
      onSquaredOff();
      onClose();
    } catch (err) {
      // Surface mode-guard 403s and broker rejections honestly — the backend
      // message tells the operator exactly what blocked the square-off.
      setErrorMsg(err instanceof Error ? err.message : "Square-off failed.");
    } finally {
      setIsSubmitting(false);
    }
  }, [position, product, exitAction, exitQty, onClose, onSquaredOff]);

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
        {errorMsg && (
          <p className="text-xs text-loss" role="alert">
            {errorMsg}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleSquareOff()}
            disabled={isSubmitting || !product}
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

interface ExitAllDialogProps {
  open: boolean;
  positionCount: number;
  target: Required<BrokerTarget>;
  onOpenChange: (open: boolean) => void;
  onExited: () => void;
}

function ExitAllDialog({ open, positionCount, target, onOpenChange, onExited }: ExitAllDialogProps) {
  const [confirmText, setConfirmText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const confirmed = confirmText.trim() === "EXIT";

  const close = useCallback(
    (next: boolean) => {
      if (!next) {
        setConfirmText("");
        setErrorMsg(null);
      }
      onOpenChange(next);
    },
    [onOpenChange],
  );

  const handleExitAll = useCallback(async () => {
    if (!confirmed) return;
    setIsSubmitting(true);
    setErrorMsg(null);
    try {
      await post("positions/exit-all", {
        confirm: true,
        broker: target.broker,
        account_id: target.account_id,
      });
      emitNotification({
        category: "system",
        title: "Exit-all submitted",
        body: "Every open position is being squared off at market.",
      });
      onExited();
      close(false);
    } catch (err) {
      // Mode-guard 403s ("live mode only", PIN unlock) and broker errors are
      // shown verbatim — never a generic failure.
      setErrorMsg(err instanceof Error ? err.message : "Exit-all positions failed.");
    } finally {
      setIsSubmitting(false);
    }
  }, [confirmed, target, onExited, close]);

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Exit all positions?</DialogTitle>
          <DialogDescription>
            This squares off EVERY open position ({positionCount}) in your live broker account at
            market price. Fills in a fast market can land far from the last traded price, and the
            action cannot be undone.
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
        {errorMsg && (
          <p className="text-xs text-loss" role="alert">
            {errorMsg}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleExitAll()}
            disabled={!confirmed || isSubmitting}
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

function PositionsWidget(props: WidgetProps) {
  const panelParams = props.params as PositionsPanelParams | undefined;
  const [view, setView] = useState<ViewMode>(() => resolveViewMode(panelParams?.view));
  const [groupMode, setGroupMode] = useState<GroupMode>(() => resolveGroupMode(panelParams?.group));

  const track = useTrackBehavior();
  const appMode = useModeStore((s) => s.mode);
  const isExplore = appMode === "explore";
  const isBrokerConnected = useBrokerConnected();
  // ONE enablement predicate for the merged widget: the host's
  // `resolveAccountReadsEnabled` (Practice reads the sandbox; Live reads a
  // connected broker; Explore reads neither and shows the labelled sample).
  // Two of the three merged widgets already used it; the third derived an
  // equivalent predicate from `useDataScope`, which is the query key's
  // concern, not the widget's.
  const accountReadsEnabled = resolveAccountReadsEnabled(appMode, isBrokerConnected);
  const canWritePositions = isBrokerConnected && appMode === "live";

  const { data: positionsData, dataUpdatedAt, isError, error, refetch, isFetching } = usePositions({
    enabled: accountReadsEnabled,
  });

  const [sorting, setSorting] = useState<SortingState>([]);
  const [convertTarget, setConvertTarget] = useState<PositionRow | null>(null);
  const [squareOffTarget, setSquareOffTarget] = useState<PositionRow | null>(null);
  const [exitAllOpen, setExitAllOpen] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  // Broker/account target for the gated convert + exit-all verbs. The OpenAlgo
  // bridge implements NEITHER verb (it would 501), so the operator picks a
  // native account (Dhan/Upstox/…) here, mirroring the orders widgets.
  const [brokerTarget, setBrokerTarget] = useBrokerOrderTarget(appMode);

  useEffect(() => {
    track("trade", `positions:view:${view}`);
  }, [track, view]);

  // ---- Data ---------------------------------------------------------------

  const rows = useMemo<PositionRow[]>(
    () => normalisePositions(isExplore ? SAMPLE_POSITION_BOOK : positionsData),
    [isExplore, positionsData],
  );

  const netRows = useMemo(() => netPositions(rows), [rows]);
  const heatRows = useMemo(() => rows.filter((row) => row.exposure > 0), [rows]);

  /** Whole-book mark-to-market — the one P&L figure, shown in every view. */
  const totalPnl = useMemo(() => totalPositionMtm(rows), [rows]);
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

  const hasUpdate = accountReadsEnabled && dataUpdatedAt > 0;
  const isStale = hasUpdate && nowMs - dataUpdatedAt > staleThresholdMs();

  // ---- Actions ------------------------------------------------------------

  const handleViewChange = useCallback(
    (next: ViewMode) => {
      if (next === view) return;
      setView(next);
      props.api.updateParameters({ ...(panelParams ?? {}), view: next });
    },
    [panelParams, props.api, view],
  );

  const handleGroupChange = useCallback(
    (next: GroupMode) => {
      setGroupMode(next);
      props.api.updateParameters({ ...(panelParams ?? {}), group: next });
    },
    [panelParams, props.api],
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

  const columns = useMemo<ColumnDef<PositionRow>[]>(
    () => [
      {
        accessorKey: "symbol",
        header: "Symbol",
        cell: ({ row }) => (
          <span className="font-mono font-medium">{row.original.symbol}</span>
        ),
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
        cell: ({ row }) => canWritePositions ? (
          <span className="inline-flex items-center gap-0.5">
            {row.original.quantity !== 0 && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setSquareOffTarget(row.original)}
                aria-label={`Square off ${row.original.symbol}`}
                title={`Square off ${row.original.symbol} at market`}
                className="h-5 px-1.5 text-xxs gap-1 text-loss hover:bg-loss/10 hover:text-loss"
              >
                <SquareX size={10} aria-hidden="true" /> Square off
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setConvertTarget(row.original)}
              aria-label={`Convert ${row.original.symbol}`}
              title={`Convert ${row.original.symbol} to another product`}
              className="h-5 px-1.5 text-xxs gap-1 text-text-muted hover:text-text-primary"
            >
              <Repeat size={10} aria-hidden="true" /> Convert
            </Button>
          </span>
        ) : (
          <span className="text-xxs text-text-muted">Live only</span>
        ),
      },
    ],
    [canWritePositions],
  );

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const emptyMessage = accountReadsEnabled || isExplore
    ? "No open positions"
    : "Connect a broker to load positions";

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs bg-surface-base" data-tour-target="positions">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 px-3 py-1.5 border-b border-border-default shrink-0 flex-wrap">
        <span className="text-xxs uppercase tracking-wider text-text-muted font-heading font-semibold">
          Positions{visibleCount > 0 ? ` (${visibleCount})` : ""}
        </span>
        <div className="flex items-center gap-2">
          {/* Provenance: what book is on screen. Separate from the capability
              chip below, which says what may be done to it. */}
          {(isExplore || appMode === "practice") && (
            <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
              {isExplore ? "Sample" : "Practice"}
            </span>
          )}
          {!isExplore && !accountReadsEnabled && (
            <span
              className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
              role="status"
              aria-label="Broker connection required for live positions"
            >
              Broker required
            </span>
          )}
          {accountReadsEnabled && appMode !== "live" && (
            <span
              className="px-1.5 py-0.5 text-xxs bg-surface-hover text-text-muted border border-border-subtle rounded"
              role="status"
              aria-label="Position management actions require Live mode"
            >
              Read-only
            </span>
          )}
          {/* Convert + Exit-all are gated native-broker verbs; pick the target
              account here (the OpenAlgo bridge implements neither). */}
          {canWritePositions && rows.length > 0 && (
            <BrokerTargetSelect value={brokerTarget} onChange={setBrokerTarget} />
          )}
          <span className={`font-mono tabular-nums font-medium ${totalPnl >= 0 ? "text-profit" : "text-loss"}`}>
            P&L: {fmtPnl(totalPnl)}
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
          {accountReadsEnabled && rows.length > 0 && (
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
          {canWritePositions && rows.length > 0 && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setExitAllOpen(true)}
              aria-label="Exit all positions"
              title="Square off every open position at market"
              className="h-5 px-1.5 text-xxs gap-1 text-loss hover:bg-loss/10 hover:text-loss"
            >
              <LogOut size={10} aria-hidden="true" /> Exit all…
            </Button>
          )}
        </div>
      </div>

      {/* Position-feed failure banner — the views keep the last good data, so
          say so instead of silently freezing the P&L. Explore never reads the
          feed, so it never shows this. */}
      {isError && !isExplore && (
        <div
          role="alert"
          className="flex items-center gap-2 px-3 py-2 mx-3 mt-2 bg-loss/10 border border-loss/20 rounded-md text-xs text-loss shrink-0"
        >
          <AlertTriangle size={12} className="shrink-0" aria-hidden="true" />
          <span className="flex-1">
            Failed to load positions — figures are frozen
            {hasUpdate ? ` at ${fmtUpdatedAt(dataUpdatedAt)}` : ""}
            {error instanceof Error && error.message ? `: ${error.message}` : "."}
          </span>
          <Button
            variant="link"
            size="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
            title="Retry the position fetch"
            className="shrink-0 h-auto p-0 text-xs font-medium text-loss hover:text-loss/80 disabled:opacity-50"
          >
            {isFetching ? "Retrying…" : "Retry"}
          </Button>
        </div>
      )}

      {/* Body */}
      {rows.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-text-muted">
          <Layers size={24} className="text-text-disabled" />
          <span className="text-sm">{emptyMessage}</span>
        </div>
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
          emptyHint={
            accountReadsEnabled || isExplore
              ? "Open positions will appear here"
              : "Live positions require a broker session"
          }
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
                  key={row.id}
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
        </div>
      )}

      {/* Explore-mode watermark */}
      {isExplore && (
        <div className="shrink-0 px-3 py-1 border-t border-border-subtle text-xxs text-text-disabled text-center">
          Sample data — connect a broker to see live positions
        </div>
      )}

      {/* Convert-position dialog — keyed so state resets per position */}
      {convertTarget && (
        <ConvertPositionDialog
          key={`${convertTarget.symbol}-${convertTarget.exchange}-${convertTarget.product}`}
          position={convertTarget}
          target={brokerTarget}
          onClose={() => setConvertTarget(null)}
          onConverted={() => void refetch()}
        />
      )}

      {/* Per-position square-off confirmation — keyed so state resets per position */}
      {squareOffTarget && (
        <SquareOffDialog
          key={`${squareOffTarget.symbol}-${squareOffTarget.exchange}-${squareOffTarget.product}-${squareOffTarget.quantity}`}
          position={squareOffTarget}
          onClose={() => setSquareOffTarget(null)}
          onSquaredOff={() => void refetch()}
        />
      )}

      {/* Exit-all typed-confirmation dialog */}
      <ExitAllDialog
        open={exitAllOpen}
        positionCount={rows.length}
        target={brokerTarget}
        onOpenChange={setExitAllOpen}
        onExited={() => void refetch()}
      />
    </div>
  );
}

export default memo(PositionsWidget);
