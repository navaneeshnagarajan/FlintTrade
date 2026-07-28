/**
 * PortfolioPivotWidget — FINOS Perspective pivot over the live position book.
 *
 * The first Perspective surface in the terminal (Phase 3 of the FINOS
 * migration): a WASM streaming pivot engine behind the framework-agnostic
 * `<perspective-viewer>` custom element. The widget feeds the viewer the
 * SAME position rows the Positions widget reads (one broker read — the
 * surfaces cannot disagree), so traders can group, aggregate, filter and
 * export the book ad hoc: P&L by product, exposure by exchange, count by
 * scrip, whatever the moment needs.
 *
 * Honesty rules: no broker → a connect affordance, never sample rows. An
 * empty book renders an empty grid with real columns (explicit schema).
 *
 * The viewer's saved view (group-bys, aggregates, filters, plugin) is
 * persisted per panel via `api.updateParameters({ viewConfig })` — a
 * PARTIAL patch, per the workspace contract. Perspective's engine runs in
 * a Web Worker; the element, table and worker are created lazily on first
 * mount and torn down on unmount.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Database, RefreshCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { usePositions } from "@/hooks/usePositions";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import type { WidgetProps } from "@/types/widgets";
import type { Position } from "@/types/api";

// ---------------------------------------------------------------------------
// Minimal structural types for the Perspective boundary (strict TS — the
// packages' own types stay behind the dynamic import).
// ---------------------------------------------------------------------------

interface PerspectiveTable {
  replace(rows: Record<string, unknown>[]): Promise<void>;
  delete(): Promise<void>;
}

interface PerspectiveClient {
  table(
    schema: Record<string, string>,
    options?: { name?: string },
  ): Promise<PerspectiveTable>;
}

/**
 * One Perspective worker per app, created lazily and shared across mounts.
 * perspective.worker() spawns a fresh dedicated WASM worker on EVERY call
 * with no library-side caching, so a per-mount client leaked one worker per
 * widget close/reopen cycle. Tables and viewers stay per-mount; only the
 * client/worker is shared (Perspective's documented one-worker-per-app
 * pattern), and it genuinely dies with the page.
 */
let perspectiveClientPromise: Promise<PerspectiveClient> | null = null;
function getPerspectiveClient(): Promise<PerspectiveClient> {
  perspectiveClientPromise ??= (async () => {
    const [{ default: perspective }] = await Promise.all([
      import("@finos/perspective"),
      import("@finos/perspective-viewer"),
      import("@finos/perspective-viewer-datagrid"),
    ]);
    return (await perspective.worker()) as unknown as PerspectiveClient;
  })();
  return perspectiveClientPromise;
}

interface PerspectiveViewerElement extends HTMLElement {
  load(table: PerspectiveTable): Promise<void>;
  restore(config: Record<string, unknown>): Promise<void>;
  save(): Promise<Record<string, unknown>>;
  delete(): Promise<void>;
}

/** Column schema for the position book — explicit so an empty book still
 * renders its columns instead of a blank inference failure. */
const POSITION_SCHEMA: Record<string, string> = {
  symbol: "string",
  exchange: "string",
  product: "string",
  quantity: "integer",
  averagePrice: "float",
  ltp: "float",
  pnl: "float",
  pnlPercent: "float",
};

function positionRows(positions: Position[]): Record<string, unknown>[] {
  return positions.map((p) => ({
    symbol: p.symbol,
    exchange: p.exchange,
    product: p.product,
    quantity: p.quantity,
    averagePrice: p.averagePrice,
    ltp: p.ltp,
    pnl: p.pnl,
    pnlPercent: p.pnlPercent,
  }));
}

type EngineState = "loading" | "ready" | "failed";

function PortfolioPivotWidget(props: WidgetProps) {
  const brokerConnected = useBrokerConnected();
  const { data: positions } = usePositions({ enabled: brokerConnected });

  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<PerspectiveViewerElement | null>(null);
  const tableRef = useRef<PerspectiveTable | null>(null);
  const configSaveTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [engineState, setEngineState] = useState<EngineState>("loading");
  const [engineEpoch, setEngineEpoch] = useState(0);

  const updateParameters = props.api.updateParameters;
  const savedViewConfig = props.params?.viewConfig as Record<string, unknown> | undefined;

  const handleRetry = useCallback(() => {
    setEngineState("loading");
    setEngineEpoch((epoch) => epoch + 1);
  }, []);

  // Boot the engine: dynamic imports (worker + custom elements), one table
  // with the explicit schema, one viewer element, saved-view restore, and
  // config-change persistence. Torn down completely on unmount.
  useEffect(() => {
    if (!brokerConnected) return;
    let cancelled = false;
    let viewer: PerspectiveViewerElement | null = null;
    let table: PerspectiveTable | null = null;
    let removeConfigListener: (() => void) | null = null;

    (async () => {
      try {
        const client = await getPerspectiveClient();
        if (cancelled) return;
        table = await client.table(POSITION_SCHEMA);
        if (cancelled) {
          void table.delete();
          return;
        }
        tableRef.current = table;

        const host = containerRef.current;
        if (!host) return;
        viewer = document.createElement("perspective-viewer") as PerspectiveViewerElement;
        viewer.setAttribute("theme", "Pro Dark");
        viewer.style.width = "100%";
        viewer.style.height = "100%";
        host.replaceChildren(viewer);
        viewerRef.current = viewer;

        await viewer.load(table);
        if (cancelled) return;
        if (savedViewConfig) {
          // A corrupt saved view must not brick the panel — fall back to
          // the default view and let the next config change overwrite it.
          try {
            await viewer.restore(savedViewConfig);
          } catch {
            /* default view stands */
          }
        }

        const onConfigUpdate = () => {
          clearTimeout(configSaveTimerRef.current);
          configSaveTimerRef.current = setTimeout(() => {
            void viewerRef.current?.save().then((viewConfig) => {
              updateParameters({ viewConfig });
            });
          }, 500);
        };
        viewer.addEventListener("perspective-config-update", onConfigUpdate);
        removeConfigListener = () =>
          viewer?.removeEventListener("perspective-config-update", onConfigUpdate);

        setEngineState("ready");
      } catch {
        if (!cancelled) setEngineState("failed");
      }
    })();

    return () => {
      cancelled = true;
      clearTimeout(configSaveTimerRef.current);
      removeConfigListener?.();
      viewerRef.current = null;
      tableRef.current = null;
      const finalViewer = viewer;
      const finalTable = table;
      void (async () => {
        try {
          await finalViewer?.delete();
          await finalTable?.delete();
        } catch {
          /* teardown is best-effort — the worker dies with the page */
        }
      })();
    };
    // savedViewConfig intentionally omitted: it is the MOUNT-time view; the
    // viewer owns the live view state and persists changes itself.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brokerConnected, engineEpoch, updateParameters]);

  // Stream the position book into the table — replace() keeps the viewer's
  // pivots/filters intact while the rows refresh underneath.
  useEffect(() => {
    if (engineState !== "ready" || !tableRef.current || !positions) return;
    void tableRef.current.replace(positionRows(positions));
  }, [engineState, positions]);

  if (!brokerConnected) {
    return (
      <div
        role="status"
        className="flex h-full flex-col items-center justify-center gap-2 px-4 text-center bg-surface-base"
        data-testid="portfolio-pivot-disconnected"
      >
        <Database className="h-8 w-8 text-text-muted" aria-hidden="true" />
        <span className="text-sm font-medium text-text-primary">Connect a broker to pivot your book</span>
        <span className="max-w-72 text-xs text-text-muted">
          The pivot reads your live position book — there is no sample mode.
        </span>
      </div>
    );
  }

  if (engineState === "failed") {
    return (
      <div
        role="alert"
        className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center bg-surface-base"
        data-testid="portfolio-pivot-failed"
      >
        <span className="text-sm text-loss">The analytics engine failed to start</span>
        <span className="max-w-72 text-xs text-text-muted">
          Perspective loads a WebAssembly worker on demand; check the console, then try again.
        </span>
        <Button size="sm" variant="outline" className="h-8 text-xs" onClick={handleRetry}>
          <RefreshCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="relative h-full w-full bg-surface-base" data-testid="portfolio-pivot-root">
      {engineState === "loading" && (
        <div
          role="status"
          className="absolute inset-0 z-10 flex items-center justify-center text-xs text-text-muted"
        >
          <span className="sr-only">Starting the analytics engine…</span>
          <span aria-hidden="true">Starting the analytics engine…</span>
        </div>
      )}
      <div ref={containerRef} className="h-full w-full" data-testid="portfolio-pivot-viewer-host" />
    </div>
  );
}

export default PortfolioPivotWidget;
