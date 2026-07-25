/**
 * LegBuilder — multi-leg option strategy builder panel.
 *
 * Adapted from openalgo-chart OptionChainPicker/strategyTemplates patterns,
 * ported to TypeScript strict mode with FlintTrade design tokens and shadcn/ui.
 *
 * Features:
 *   - Up to 4 legs, each with BUY/SELL + CE/PE + strike select + lots
 *   - Strategy template pills drawn from the shared `lib/strategyTemplates`
 *     catalogue: Short Straddle, Short Strangle, Bull Call Spread, Bear Put
 *     Spread, Iron Condor, Butterfly, Custom. The two credit strategies were
 *     previously labelled just "Straddle"/"Strangle" here while the very same
 *     ids meant the LONG (debit) versions in the other two catalogues — this
 *     panel places REAL gated basket orders, so the direction is now named.
 *   - ATM-relative template auto-population with nearest-strike snapping
 *   - Net premium, max profit, max loss, breakeven(s) via payoff scan
 *   - Place Strategy button dispatches basketOrder through the gated backend
 *     basket route (SafetySystem L1–L5 → gate_order → BrokerRouter per leg)
 *   - BUY legs: profit tint background; SELL legs: loss tint background
 *   - forwardRef exposes addLegFromStrike so OptionChainWidget can push
 *     strike-click events in when the panel is open
 */

import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { Plus, Trash2, TrendingUp, Zap } from "lucide-react";
import { basketOrder, OrderApiError } from "@/services/api";
import type { BasketOrderResult } from "@/types/api";
import { buildCompactOptionSymbol } from "@/lib/optionSymbols";
import {
  builderLegsFor,
  getStrategyTemplate,
  CUSTOM_TEMPLATE_ID,
  type StrategyTemplate,
} from "@/lib/strategyTemplates";
import { NUM, NUM0, fmtLtp } from "./formatters";
import type { StrikeRow } from "./types";
import PayoffChart from "./PayoffChart";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

// ---------------------------------------------------------------------------
// Feature availability
// ---------------------------------------------------------------------------

/**
 * Whether multi-leg strategy placement is wired in this build.
 *
 * "Place Strategy" dispatches `basketOrder`, which posts to the backend basket
 * route (`POST /api/v1/orders/basket` in `flinttrade_core.order_routes`). That
 * route is live now: it sits behind `require_live_unlocked` + order rate
 * limiting, pre-admits the whole basket through SafetySystem L1–L5, then
 * executes atomically-with-rollback via the engine `BasketOrderExecutor`
 * whose `place_leg` is the gated dispatcher (`gate_order` one-shot HMAC
 * `SafetyContext` → `BrokerRouter` → broker adapter). The flag is kept as an
 * honest degrade switch: should the executor ever be unbound again (the route
 * then fails closed with a 503), flip it back to `false` so the button shows
 * "Coming soon" instead of surfacing raw 503 toasts.
 */
const STRATEGY_PLACEMENT_AVAILABLE: boolean = true;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OptionLeg {
  id: string;
  side: "BUY" | "SELL";
  optionType: "CE" | "PE";
  strike: number;
  lots: number;
  /** LTP from option chain at time of leg creation/refresh */
  premium: number | null;
}

export interface LegBuilderHandle {
  /** Called by OptionChainWidget when user clicks a chain row while builder is open */
  addLegFromStrike: (strike: number, optionType: "CE" | "PE") => void;
}

export interface LegBuilderProps {
  /** Strikes from loaded option chain — used to populate strike selectors */
  strikes: StrikeRow[];
  /** ATM strike (null while chain is loading) */
  atmStrike: number | null;
  /** Lot size for the underlying */
  lotSize: number;
  /** Symbol label, e.g. "NIFTY" */
  symLabel: string;
  /** Exchange, e.g. "NFO" */
  exchange: string;
  /** Selected expiry string, e.g. "2026-04-10" */
  expiry: string | null;
  /** Close the panel */
  onClose: () => void;
  /** Current live spot price for the payoff chart marker (falls back to atmStrike) */
  spotPrice?: number;
}

// ---------------------------------------------------------------------------
// Strategy template pills
// ---------------------------------------------------------------------------

/**
 * The catalogue entries this panel offers, in pill order. Every leg shape and
 * label comes from `lib/strategyTemplates`; only the selection and ordering are
 * local. The credit strategies are the explicitly-short ids — this panel has
 * always sold both legs, it just used to call that "Straddle".
 */
const TEMPLATE_ORDER = [
  "short-straddle",
  "short-strangle",
  "bull-call-spread",
  "bear-put-spread",
  // The credit verticals. Added when Spread View was demoted to template
  // data: a retired Spread View panel rehydrates onto the option chain, and
  // two of its four spread types were unreachable from this builder — the
  // only surface that can price them against a live chain and place them.
  "bull-put-spread",
  "bear-call-spread",
  "iron-condor",
  "butterfly",
  CUSTOM_TEMPLATE_ID,
] as const;

/** Resolved pill definitions — a missing id would be a catalogue regression. */
const TEMPLATE_PILLS: StrategyTemplate[] = TEMPLATE_ORDER.flatMap((id) => {
  const tmpl = getStrategyTemplate(id);
  return tmpl ? [tmpl] : [];
});

const DEFAULT_TEMPLATE_ID: string = TEMPLATE_ORDER[0];

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

function generateId(): string {
  return `leg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

/** Derive the most common strike gap from a sorted chain */
function inferStrikeGap(strikes: StrikeRow[]): number {
  if (strikes.length < 2) return 50;
  const sorted = [...strikes].map((r) => r.strike).sort((a, b) => a - b);
  return sorted[1] - sorted[0];
}

/**
 * P&L payoff for a single leg at expiry.
 * Returns rupee value (lots × lotSize already multiplied in).
 */
function legPayoff(leg: OptionLeg, spotAtExpiry: number, lotSize: number): number {
  const intrinsic =
    leg.optionType === "CE"
      ? Math.max(0, spotAtExpiry - leg.strike)
      : Math.max(0, leg.strike - spotAtExpiry);
  const prem = leg.premium ?? 0;
  const sign = leg.side === "BUY" ? 1 : -1;
  return sign * (intrinsic - prem) * leg.lots * lotSize;
}

interface PayoffMetrics {
  netPremiumRupees: number;  // positive = debit, negative = credit
  maxProfit: number | null;
  maxLoss:   number | null;
  breakevens: number[];
}

function computePayoff(legs: OptionLeg[], lotSize: number): PayoffMetrics {
  if (legs.length === 0) {
    return { netPremiumRupees: 0, maxProfit: null, maxLoss: null, breakevens: [] };
  }

  // Net premium (debit/credit) across all legs
  const netPremiumRupees = legs.reduce((sum, leg) => {
    const prem = leg.premium ?? 0;
    const sign = leg.side === "BUY" ? 1 : -1;
    return sum + sign * prem * leg.lots * lotSize;
  }, 0);

  // Scan a range of spot prices to find max profit, max loss, and breakevens
  const strikeValues = legs.map((l) => l.strike);
  const lo = Math.max(0, Math.min(...strikeValues) - Math.max(...strikeValues) * 0.15);
  const hi = Math.max(...strikeValues) * 1.15;
  const STEPS = 400;
  const step = (hi - lo) / STEPS;

  let maxP = -Infinity;
  let maxL =  Infinity;
  const points: number[] = [];

  for (let i = 0; i <= STEPS; i++) {
    const spot = lo + i * step;
    const pnl  = legs.reduce((s, leg) => s + legPayoff(leg, spot, lotSize), 0);
    if (pnl > maxP) maxP = pnl;
    if (pnl < maxL) maxL = pnl;
    points.push(pnl);
  }

  // Breakeven crossings (sign change between adjacent sample points)
  const bks: number[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    if ((a < 0 && b >= 0) || (a >= 0 && b < 0)) {
      const spotA = lo + i * step;
      const spotB = lo + (i + 1) * step;
      // Linear interpolation to find zero crossing
      const bk = spotA + (spotB - spotA) * (-a / (b - a));
      bks.push(Math.round(bk));
    }
  }

  return {
    netPremiumRupees,
    maxProfit: maxP === -Infinity ? null : Math.round(maxP),
    maxLoss:   maxL ===  Infinity ? null : Math.round(maxL),
    breakevens: bks,
  };
}

// ---------------------------------------------------------------------------
// Basket partial-failure surfacing
// ---------------------------------------------------------------------------

/** Toast message state: `urgent` messages never auto-dismiss and render as alerts. */
interface OrderMsg {
  text: string;
  ok: boolean;
  urgent?: boolean;
}

/** Narrow an `OrderApiError.body` to the 422 `BasketOrderResult` shape. */
function isBasketOrderResult(body: unknown): body is BasketOrderResult {
  if (typeof body !== "object" || body === null) return false;
  const b = body as Partial<BasketOrderResult>;
  return (
    typeof b.placed_count === "number"
    && typeof b.failed_count === "number"
    && Array.isArray(b.legs)
  );
}

/**
 * Build the honest toast for a 422 basket partial/total failure.
 *
 * The backend basket executor marks a rollback it ATTEMPTED but could not
 * confirm as `rolled_back: true` with an empty `rollback_order_id`
 * (basket_orders.py `_rollback`): that leg was really placed and may still be
 * open on the broker. That state must surface as an urgent, non-dismissing
 * warning — a bare first-error toast would hide live naked legs.
 */
function describeBasketFailure(result: BasketOrderResult, serverMsg: string): OrderMsg {
  const rollbackUnconfirmed = result.legs.some(
    (leg) => leg.rolled_back && leg.rollback_order_id === "",
  );
  const placedLabel = `${result.placed_count} leg${result.placed_count === 1 ? "" : "s"} placed`;
  const rolledBackNote =
    result.placed_count > 0 && result.rolled_back && !rollbackUnconfirmed ? " then rolled back" : "";
  let text = `${placedLabel}${rolledBackNote}, ${result.failed_count} failed`;
  if (serverMsg) text += ` — ${serverMsg}`;
  if (rollbackUnconfirmed) text += ". Rollback unconfirmed — check Positions.";
  return { text, ok: false, urgent: rollbackUnconfirmed };
}

// ---------------------------------------------------------------------------
// LegRow sub-component
// ---------------------------------------------------------------------------

interface LegRowProps {
  leg: OptionLeg;
  strikes: StrikeRow[];
  onChangeSide:   (id: string, side: "BUY" | "SELL") => void;
  onChangeType:   (id: string, type: "CE" | "PE") => void;
  onChangeStrike: (id: string, strike: number) => void;
  onChangeLots:   (id: string, lots: number) => void;
  onRemove:       (id: string) => void;
}

function LegRow({
  leg,
  strikes,
  onChangeSide,
  onChangeType,
  onChangeStrike,
  onChangeLots,
  onRemove,
}: LegRowProps) {
  const isBuy = leg.side === "BUY";

  return (
    <div
      className={`flex items-center gap-1.5 px-2 py-1 rounded border text-xs ${
        isBuy
          ? "bg-profit/5 border-profit/20"
          : "bg-loss/5 border-loss/20"
      }`}
    >
      {/* BUY / SELL toggle */}
      <div className="flex rounded overflow-hidden border border-border-default shrink-0" role="group" aria-label="Side">
        <button
          onClick={() => onChangeSide(leg.id, "BUY")}
          aria-label="Buy"
          aria-pressed={isBuy}
          className={`px-1.5 py-0.5 text-xxs font-bold transition-colors ${
            isBuy
              ? "bg-profit text-white"
              : "bg-surface-hover text-text-muted hover:text-text-primary"
          }`}
        >
          B
        </button>
        <button
          onClick={() => onChangeSide(leg.id, "SELL")}
          aria-label="Sell"
          aria-pressed={!isBuy}
          className={`px-1.5 py-0.5 text-xxs font-bold transition-colors ${
            !isBuy
              ? "bg-loss text-white"
              : "bg-surface-hover text-text-muted hover:text-text-primary"
          }`}
        >
          S
        </button>
      </div>

      {/* CE / PE toggle */}
      <div className="flex rounded overflow-hidden border border-border-default shrink-0">
        <button
          onClick={() => onChangeType(leg.id, "CE")}
          className={`px-1.5 py-0.5 text-xxs font-bold transition-colors ${
            leg.optionType === "CE"
              ? "bg-accent/20 text-accent border-r border-accent/30"
              : "bg-surface-hover text-text-muted hover:text-text-primary border-r border-border-default"
          }`}
        >
          CE
        </button>
        <button
          onClick={() => onChangeType(leg.id, "PE")}
          className={`px-1.5 py-0.5 text-xxs font-bold transition-colors ${
            leg.optionType === "PE"
              ? "bg-accent/20 text-accent"
              : "bg-surface-hover text-text-muted hover:text-text-primary"
          }`}
        >
          PE
        </button>
      </div>

      {/* Strike selector */}
      <Select value={String(leg.strike)} onValueChange={(v) => onChangeStrike(leg.id, Number(v))}>
        <SelectTrigger className="flex-1 min-w-0 h-6 px-1 text-xs font-mono" aria-label="Strike price">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {strikes.map((r) => (
            <SelectItem key={r.strike} value={String(r.strike)} className="text-xs font-mono">
              {NUM0.format(r.strike)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Lots */}
      <input
        type="number"
        min={1}
        max={99}
        value={leg.lots}
        onChange={(e) => {
          const val = parseInt(e.target.value, 10);
          if (!isNaN(val) && val >= 1 && val <= 99) onChangeLots(leg.id, val);
        }}
        className="w-10 bg-surface-base border border-border-default text-text-primary text-xs font-mono rounded px-1 py-0.5 text-center focus:outline-none focus:ring-1 focus:ring-accent/40"
        aria-label="Number of lots"
      />

      {/* Premium badge */}
      <span className="text-xxs text-text-muted font-mono w-12 text-right shrink-0">
        {leg.premium != null ? fmtLtp(leg.premium) : "—"}
      </span>

      {/* Remove leg */}
      <button
        onClick={() => onRemove(leg.id)}
        className="text-text-muted hover:text-loss transition-colors shrink-0"
        aria-label="Remove leg"
      >
        <Trash2 size={11} />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// LegBuilder — main component (forwardRef to expose addLegFromStrike)
// ---------------------------------------------------------------------------

const LegBuilder = forwardRef<LegBuilderHandle, LegBuilderProps>(function LegBuilder(
  { strikes, atmStrike, lotSize, symLabel, exchange, expiry, onClose, spotPrice },
  ref,
) {
  const [legs, setLegs]           = useState<OptionLeg[]>([]);
  const [activeTemplate, setActiveTemplate] = useState<string>(DEFAULT_TEMPLATE_ID);
  const [placing, setPlacing]     = useState(false);
  const [orderMsg, setOrderMsg]   = useState<OrderMsg | null>(null);
  const orderMsgTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (orderMsgTimerRef.current !== null) {
        clearTimeout(orderMsgTimerRef.current);
      }
    };
  }, []);

  /**
   * Show a toast, clearing any pending auto-dismiss first so a stale timer from
   * an earlier toast can never wipe a fresh one. Urgent messages (unconfirmed
   * rollback — possibly live naked legs) never auto-dismiss: they persist until
   * the next placement attempt replaces them.
   */
  const showOrderMsg = useCallback((msg: OrderMsg) => {
    if (orderMsgTimerRef.current !== null) {
      clearTimeout(orderMsgTimerRef.current);
      orderMsgTimerRef.current = null;
    }
    setOrderMsg(msg);
    if (!msg.urgent) {
      orderMsgTimerRef.current = setTimeout(() => setOrderMsg(null), 4000);
    }
  }, []);

  const strikeGap = useMemo(() => inferStrikeGap(strikes), [strikes]);

  /** Look up live LTP from the option chain for a given strike + type */
  const premiumFor = useCallback(
    (strike: number, optionType: "CE" | "PE"): number | null => {
      const row = strikes.find((r) => r.strike === strike);
      if (!row) return null;
      const side = optionType === "CE" ? row.call : row.put;
      return side?.ltp ?? side?.last_price ?? null;
    },
    [strikes],
  );

  /** Refresh all leg premiums from the current chain snapshot */
  const refreshPremiums = useCallback(
    (legList: OptionLeg[]): OptionLeg[] =>
      legList.map((leg) => ({
        ...leg,
        premium: premiumFor(leg.strike, leg.optionType) ?? leg.premium,
      })),
    [premiumFor],
  );

  // ---------------------------------------------------------------------------
  // Template application
  // ---------------------------------------------------------------------------

  const applyTemplate = useCallback(
    (templateKey: string) => {
      setActiveTemplate(templateKey);
      if (templateKey === CUSTOM_TEMPLATE_ID) {
        // Custom: clear legs so user builds from scratch
        setLegs([]);
        return;
      }

      const tmpl = getStrategyTemplate(templateKey);
      if (!tmpl || !atmStrike || strikes.length === 0) return;
      // Same gate the other consumers use: reference-only entries (stock or
      // multi-expiry legs) never yield builder legs, so they can never be
      // half-loaded into a panel that places live orders.
      const templateLegs = builderLegsFor(tmpl);
      if (!templateLegs) return;

      const sortedStrikeValues = strikes.map((r) => r.strike).sort((a, b) => a - b);
      const newLegs: OptionLeg[] = [];

      for (const tl of templateLegs) {
        const target = atmStrike + tl.strikeOffset * strikeGap;
        // Snap to the nearest available strike in the chain
        const nearest = sortedStrikeValues.reduce((prev, curr) =>
          Math.abs(curr - target) < Math.abs(prev - target) ? curr : prev,
          sortedStrikeValues[0],
        );

        newLegs.push({
          id: generateId(),
          side: tl.action,
          optionType: tl.optionType,
          strike: nearest,
          lots: tl.lots,
          premium: premiumFor(nearest, tl.optionType),
        });
      }

      setLegs(refreshPremiums(newLegs));
    },
    [atmStrike, strikes, strikeGap, premiumFor, refreshPremiums],
  );

  // ---------------------------------------------------------------------------
  // Leg CRUD
  // ---------------------------------------------------------------------------

  const addBlankLeg = useCallback(() => {
    if (legs.length >= 4) return;
    const defaultStrike =
      atmStrike ??
      strikes[Math.floor(strikes.length / 2)]?.strike ??
      0;
    setLegs((prev) => [
      ...prev,
      {
        id: generateId(),
        side: "BUY",
        optionType: "CE",
        strike: defaultStrike,
        lots: 1,
        premium: premiumFor(defaultStrike, "CE"),
      },
    ]);
    setActiveTemplate(CUSTOM_TEMPLATE_ID);
  }, [legs.length, atmStrike, strikes, premiumFor]);

  const removeLeg = useCallback((id: string) => {
    setLegs((prev) => prev.filter((l) => l.id !== id));
  }, []);

  const updateLeg = useCallback(
    (id: string, patch: Partial<OptionLeg>) => {
      setLegs((prev) =>
        prev.map((l) => {
          if (l.id !== id) return l;
          const updated = { ...l, ...patch };
          // Refresh premium whenever strike or option type changes
          if ("strike" in patch || "optionType" in patch) {
            updated.premium = premiumFor(updated.strike, updated.optionType);
          }
          return updated;
        }),
      );
    },
    [premiumFor],
  );

  /**
   * Called from OptionChainWidget when the user clicks a strike row.
   * Toggles the leg (adds if absent, removes if present).
   * Exposed via the forwarded ref as LegBuilderHandle.addLegFromStrike.
   */
  const addLegFromStrike = useCallback(
    (strike: number, optionType: "CE" | "PE") => {
      setLegs((prev) => {
        const existingIdx = prev.findIndex(
          (l) => l.strike === strike && l.optionType === optionType,
        );
        if (existingIdx >= 0) {
          // Toggle off
          return prev.filter((_, i) => i !== existingIdx);
        }
        if (prev.length >= 4) return prev; // silently cap at 4
        return [
          ...prev,
          {
            id: generateId(),
            side: "BUY",
            optionType,
            strike,
            lots: 1,
            premium: premiumFor(strike, optionType),
          },
        ];
      });
      setActiveTemplate(CUSTOM_TEMPLATE_ID);
    },
    [premiumFor],
  );

  // Expose imperative API to parent
  useImperativeHandle(ref, () => ({ addLegFromStrike }), [addLegFromStrike]);

  // ---------------------------------------------------------------------------
  // Payoff metrics (recalculated on legs / lotSize change)
  // ---------------------------------------------------------------------------

  const metrics = useMemo(() => computePayoff(legs, lotSize), [legs, lotSize]);

  // ---------------------------------------------------------------------------
  // Order placement
  // ---------------------------------------------------------------------------

  async function handlePlaceStrategy() {
    if (legs.length < 1) return;
    if (!STRATEGY_PLACEMENT_AVAILABLE) {
      // Honest degrade path — only reachable if the availability flag is
      // flipped back off (e.g. the backend basket executor is unbound again).
      showOrderMsg({ text: "Strategy placement coming soon", ok: false });
      return;
    }
    if (!expiry) {
      setOrderMsg({ text: "Select an expiry first", ok: false });
      return;
    }

    setPlacing(true);

    try {
      // All legs are MARKET/MIS — price and trigger price are intentionally
      // omitted so the backend BasketLeg parses them as None.
      const orders = legs.map((leg) => ({
        symbol:    buildCompactOptionSymbol(symLabel, expiry, leg.strike, leg.optionType)
          ?? `${symLabel}${expiry}${leg.strike}${leg.optionType}`,
        exchange,
        action:    leg.side,
        quantity:  leg.lots * lotSize,
        orderType: "MARKET" as const,
        product:   "MIS" as const,
      }));

      const result = await basketOrder({ strategy: "FlintLegBuilder", orders });
      const placed = result.placed_count;
      showOrderMsg({ text: `${placed} leg${placed === 1 ? "" : "s"} placed`, ok: true });
    } catch (e) {
      // A 422 from the basket route carries the full per-leg truth in the
      // error body — surface placed/failed counts (and the urgent
      // rollback-unconfirmed warning) instead of only the first error string.
      if (e instanceof OrderApiError && e.status === 422 && isBasketOrderResult(e.body)) {
        showOrderMsg(describeBasketFailure(e.body, e.message));
      } else {
        showOrderMsg({ text: (e as Error).message || "Order failed", ok: false });
      }
    } finally {
      setPlacing(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------

  const canAddLeg = legs.length < 4;
  const canPlace  = STRATEGY_PLACEMENT_AVAILABLE && legs.length >= 1 && !placing;

  const isDebit       = metrics.netPremiumRupees >= 0;
  const netPremLabel  = isDebit ? "Debit" : "Credit";
  const netPremAbs    = Math.abs(metrics.netPremiumRupees);

  // ---------------------------------------------------------------------------
  // JSX
  // ---------------------------------------------------------------------------

  return (
    <div
      className="flex-none bg-surface-card border-b border-border-default"
      role="region"
      aria-label="Strategy leg builder"
    >
      {/* ── Header + template pills ─────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-2 py-1.5 border-b border-border-default">
        <TrendingUp size={12} className="text-accent shrink-0" />
        <span className="text-xs font-semibold text-text-primary uppercase tracking-wide">
          Strategy Builder
        </span>

        {/* Template pills — scrollable row */}
        <div
          className="flex items-center gap-1 flex-1 min-w-0 overflow-x-auto"
          role="group"
          aria-label="Strategy templates"
        >
          {TEMPLATE_PILLS.map((tmpl) => {
            const active = activeTemplate === tmpl.id;
            return (
              <button
                key={tmpl.id}
                onClick={() => applyTemplate(tmpl.id)}
                title={`${tmpl.name} — ${tmpl.description}`}
                aria-label={tmpl.name}
                aria-pressed={active}
                className={`shrink-0 px-2 py-0.5 text-xxs font-semibold rounded-full border transition-colors ${
                  active
                    ? "bg-accent/20 border-accent/50 text-accent"
                    : "bg-surface-base border-border-default text-text-muted hover:text-text-primary hover:border-accent/30"
                }`}
              >
                {tmpl.shortName}
              </button>
            );
          })}
        </div>

        {/* Close button */}
        <button
          onClick={onClose}
          className="shrink-0 text-text-muted hover:text-text-primary transition-colors px-1 py-0.5 rounded hover:bg-surface-hover text-xxs"
          aria-label="Close strategy builder"
        >
          ✕
        </button>
      </div>

      {/* ── Leg rows ────────────────────────────────────────────────────── */}
      <div className="px-2 py-1.5 space-y-1">
        {legs.length === 0 ? (
          <p className="text-xs text-text-muted py-1">
            Choose a template above, or click{" "}
            <strong className="text-text-primary">+ Add Leg</strong> to build
            custom. Click any chain row to add that strike.
          </p>
        ) : (
          <>
            {/* Column header labels */}
            <div className="flex items-center gap-1.5 px-2 text-xxs text-text-muted">
              <span className="w-10 shrink-0">Side</span>
              <span className="w-11 shrink-0">Type</span>
              <span className="flex-1">Strike</span>
              <span className="w-10 text-center">Lots</span>
              <span className="w-12 text-right">LTP</span>
              <span className="w-5" />
            </div>

            {legs.map((leg) => (
              <LegRow
                key={leg.id}
                leg={leg}
                strikes={strikes}
                onChangeSide={(id, side) => updateLeg(id, { side })}
                onChangeType={(id, optionType) => updateLeg(id, { optionType })}
                onChangeStrike={(id, strike) => updateLeg(id, { strike })}
                onChangeLots={(id, lots) => updateLeg(id, { lots })}
                onRemove={removeLeg}
              />
            ))}
          </>
        )}

        {/* Add leg (capped at 4) */}
        {canAddLeg && (
          <button
            onClick={addBlankLeg}
            className="flex items-center gap-1 text-xxs text-text-muted hover:text-accent transition-colors px-2 py-0.5 rounded hover:bg-surface-hover"
          >
            <Plus size={10} aria-hidden="true" />
            Add Leg{legs.length > 0 ? ` (${legs.length}/4)` : ""}
          </button>
        )}
      </div>

      {/* ── Metrics footer + Place Strategy ─────────────────────────────── */}
      {legs.length > 0 && (
        <div className="px-2 py-1.5 border-t border-border-default flex items-center gap-3 flex-wrap">

          {/* Net premium */}
          <div className="flex items-center gap-1 text-xs font-mono">
            <span className="text-xxs text-text-muted font-sans">Net</span>
            <span
              className={
                netPremAbs === 0
                  ? "text-text-muted"
                  : isDebit
                  ? "text-loss"
                  : "text-profit"
              }
            >
              {netPremLabel} {NUM.format(netPremAbs)}
            </span>
          </div>

          {/* Max profit */}
          {metrics.maxProfit != null && (
            <div className="flex items-center gap-1 text-xs font-mono">
              <span className="text-xxs text-text-muted font-sans">Max P</span>
              <span className={metrics.maxProfit > 0 ? "text-profit" : "text-text-muted"}>
                {NUM0.format(metrics.maxProfit)}
              </span>
            </div>
          )}

          {/* Max loss */}
          {metrics.maxLoss != null && (
            <div className="flex items-center gap-1 text-xs font-mono">
              <span className="text-xxs text-text-muted font-sans">Max L</span>
              <span className={metrics.maxLoss < 0 ? "text-loss" : "text-text-muted"}>
                {NUM0.format(metrics.maxLoss)}
              </span>
            </div>
          )}

          {/* Breakeven(s) — show up to 2 */}
          {metrics.breakevens.length > 0 && (
            <div className="flex items-center gap-1 text-xs font-mono">
              <span className="text-xxs text-text-muted font-sans">B/E</span>
              <span className="text-atm-text">
                {metrics.breakevens
                  .slice(0, 2)
                  .map((b) => NUM0.format(b))
                  .join(" / ")}
              </span>
            </div>
          )}

          {/* Lot size note */}
          <span className="text-xxs text-text-muted font-mono ml-auto">
            Lot {lotSize}
          </span>

          {/* Place Strategy — dispatches the gated basket route; the "Coming
              soon" branches only render if the availability flag is turned
              back off (honest degrade, never a raw 503 toast) */}
          <button
            onClick={() => void handlePlaceStrategy()}
            disabled={!canPlace}
            title={
              STRATEGY_PLACEMENT_AVAILABLE
                ? undefined
                : "Strategy placement is coming soon"
            }
            aria-label={
              STRATEGY_PLACEMENT_AVAILABLE
                ? "Place strategy"
                : "Place strategy (coming soon)"
            }
            className="flex items-center gap-1 px-3 py-0.5 text-xs font-semibold rounded bg-accent/20 text-accent border border-accent/40 hover:bg-accent/30 hover:border-accent/60 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Zap size={11} />
            {!STRATEGY_PLACEMENT_AVAILABLE
              ? "Coming soon"
              : placing
              ? "Placing…"
              : "Place Strategy"}
          </button>
        </div>
      )}

      {/* ── Payoff chart ─────────────────────────────────────────────────── */}
      {legs.length > 0 && (
        <PayoffChart
          legs={legs}
          spotPrice={spotPrice ?? atmStrike ?? 0}
          lotSize={lotSize}
          maxProfit={metrics.maxProfit}
          maxLoss={metrics.maxLoss}
          breakevens={metrics.breakevens}
        />
      )}

      {/* ── Order toast ─────────────────────────────────────────────────── */}
      {orderMsg && (
        <div
          className={`px-2 py-1 text-xs border-t ${
            orderMsg.ok
              ? "bg-profit/10 border-profit/20 text-profit"
              : orderMsg.urgent
              ? "bg-loss/20 border-loss/40 text-loss font-semibold"
              : "bg-loss/10 border-loss/20 text-loss"
          }`}
          role={orderMsg.urgent ? "alert" : "status"}
          aria-live={orderMsg.urgent ? "assertive" : "polite"}
        >
          {orderMsg.text}
        </div>
      )}
    </div>
  );
});

export default LegBuilder;
