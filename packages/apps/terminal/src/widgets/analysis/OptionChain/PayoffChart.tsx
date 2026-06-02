/**
 * PayoffChart — options strategy payoff adapter.
 *
 * Computes multi-leg option strategy payoff samples and delegates chart
 * rendering, markers, and hover behaviour to the shared Flint chart core.
 */

import { useMemo } from "react";
import { FlintPayoffChart, type FlintPayoffPoint } from "@flinttrade/design-system";
import type { OptionLeg } from "./LegBuilder";
import { NUM0 } from "./formatters";

export interface PayoffChartProps {
  legs: OptionLeg[];
  spotPrice: number;
  lotSize: number;
  maxProfit: number | null;
  maxLoss: number | null;
  breakevens: number[];
}

const VIEWBOX_W = 600;
const VIEWBOX_H = 220;
const SAMPLES = 300;

function singleLegPayoff(leg: OptionLeg, spot: number, lotSize: number): number {
  const intrinsic =
    leg.optionType === "CE"
      ? Math.max(0, spot - leg.strike)
      : Math.max(0, leg.strike - spot);
  const premium = leg.premium ?? 0;
  const direction = leg.side === "BUY" ? 1 : -1;
  return direction * (intrinsic - premium) * leg.lots * lotSize;
}

function totalPayoff(legs: readonly OptionLeg[], spot: number, lotSize: number): number {
  return legs.reduce((sum, leg) => sum + singleLegPayoff(leg, spot, lotSize), 0);
}

function fmtAxisPnl(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1_00_00_000) return `${sign}${(abs / 1_00_00_000).toFixed(1)}Cr`;
  if (abs >= 1_00_000) return `${sign}${(abs / 1_00_000).toFixed(1)}L`;
  if (abs >= 1_000) return `${sign}${(abs / 1_000).toFixed(0)}K`;
  return `${sign}${abs.toFixed(0)}`;
}

function fmtAxisSpot(value: number): string {
  if (value >= 1_00_000) return `${(value / 1_000).toFixed(0)}K`;
  return NUM0.format(value);
}

function buildTicks(min: number, max: number, limit = 8): number[] {
  const range = max - min || 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(range)));
  const step = magnitude >= range / 3
    ? magnitude / 5
    : magnitude >= range / 6
    ? magnitude / 2
    : magnitude;
  const ticks: number[] = [];
  const startTick = Math.ceil(min / step) * step;
  for (let value = startTick; value <= max + step * 0.01; value += step) {
    ticks.push(parseFloat(value.toFixed(10)));
  }
  return ticks.slice(0, limit);
}

function buildSpotTicks(min: number, max: number, limit = 8): number[] {
  const range = max - min || 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(range)));
  const step = magnitude >= range / 3
    ? magnitude / 2
    : magnitude >= range / 5
    ? magnitude
    : magnitude * 2;
  const ticks: number[] = [];
  const startTick = Math.ceil(min / step) * step;
  for (let value = startTick; value <= max + step * 0.01; value += step) {
    ticks.push(parseFloat(value.toFixed(10)));
  }
  return ticks.slice(0, limit);
}

export default function PayoffChart({
  legs,
  spotPrice,
  lotSize,
  maxProfit,
  maxLoss,
  breakevens,
}: PayoffChartProps) {
  const { xMin, xMax, strikes } = useMemo(() => {
    const strikePrices = legs.map((leg) => leg.strike);
    if (strikePrices.length === 0) {
      const fallback = spotPrice > 0 ? spotPrice : 1000;
      return {
        xMin: fallback * 0.85,
        xMax: fallback * 1.15,
        strikes: [] as number[],
      };
    }

    const minStrike = Math.min(...strikePrices);
    const maxStrike = Math.max(...strikePrices);
    return {
      xMin: minStrike * 0.85,
      xMax: maxStrike * 1.15,
      strikes: Array.from(new Set(strikePrices)).sort((a, b) => a - b),
    };
  }, [legs, spotPrice]);

  const points = useMemo<FlintPayoffPoint[]>(() => {
    const step = (xMax - xMin) / SAMPLES;
    return Array.from({ length: SAMPLES + 1 }, (_, index) => {
      const spot = xMin + index * step;
      return { x: spot, y: totalPayoff(legs, spot, lotSize) };
    });
  }, [legs, lotSize, xMin, xMax]);

  const { yMin, yMax } = useMemo(() => {
    const pnlValues = points.map((point) => point.y);
    const rawMin = Math.min(...pnlValues);
    const rawMax = Math.max(...pnlValues);
    const range = rawMax - rawMin || 1;
    const padding = range * 0.12;
    return {
      yMin: rawMin - padding,
      yMax: rawMax + padding,
    };
  }, [points]);

  const xTicks = useMemo(() => buildSpotTicks(xMin, xMax), [xMin, xMax]);
  const yTicks = useMemo(() => buildTicks(yMin, yMax), [yMin, yMax]);

  return (
    <div className="w-full px-2 pb-2 pt-1">
      <FlintPayoffChart
        ariaLabel="Options payoff chart"
        points={points}
        xDomain={[xMin, xMax]}
        yDomain={[yMin, yMax]}
        xTicks={xTicks}
        yTicks={yTicks}
        xFormatter={fmtAxisSpot}
        yFormatter={fmtAxisPnl}
        strikeMarkers={strikes}
        breakevens={breakevens}
        spotPrice={spotPrice > 0 ? spotPrice : null}
        maxProfit={maxProfit}
        maxLoss={maxLoss}
        breakevenColor="var(--color-atm-text, #e8c97a)"
        width={VIEWBOX_W}
        height={VIEWBOX_H}
        interactive
        className="h-auto select-none"
      />
    </div>
  );
}
