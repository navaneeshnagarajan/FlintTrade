/**
 * Deterministic sample option chain for OI Analytics' disconnected state.
 *
 * It is fabricated, and every surface that renders it carries the "Sample
 * data" provenance badge. It exists so the widget is explorable without a
 * broker; it must never be presented as live open interest.
 *
 * The generator is SEEDED. The sample chain used to be built with
 * `Math.random()` at module scope, so the same "sample" showed different open
 * interest on every page load and no test could pin it.
 */

import type { StrikeCell } from "./oiStrikes";

function seeded(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 1_103_515_245 + 12_345) % 2_147_483_648;
    return state / 2_147_483_648;
  };
}

export interface SampleStrike {
  strike: number;
  ceOi: number;
  peOi: number;
  ceOiChange: number;
  peOiChange: number;
  ceVolume: number;
  peVolume: number;
}

export function buildSampleChain(baseStrike: number, step: number, count: number): SampleStrike[] {
  const rand = seeded(20_260_725);
  return Array.from({ length: count }, (_, i) => {
    const strike = baseStrike - Math.floor(count / 2) * step + i * step;
    const distFromATM = Math.abs(i - Math.floor(count / 2));
    const ceOi = Math.round((500_000 - distFromATM * 30_000) * (0.8 + rand() * 0.4));
    const peOi = Math.round((480_000 - distFromATM * 25_000) * (0.8 + rand() * 0.4));
    return {
      strike,
      ceOi: Math.max(10_000, ceOi),
      peOi: Math.max(10_000, peOi),
      ceOiChange: Math.round((rand() - 0.5) * 40_000),
      peOiChange: Math.round((rand() - 0.5) * 35_000),
      ceVolume: Math.round(ceOi * 0.3 * rand()),
      peVolume: Math.round(peOi * 0.3 * rand()),
    };
  });
}

export const SAMPLE_ATM = 24_750;

/** The sample chain in the same shape the live views consume. */
export const SAMPLE_STRIKE_CELLS: StrikeCell[] = buildSampleChain(SAMPLE_ATM, 50, 21).map(
  (row) => ({
    strike: row.strike,
    ceOi: row.ceOi,
    peOi: row.peOi,
    ceOiChange: row.ceOiChange,
    peOiChange: row.peOiChange,
    ceVolume: row.ceVolume,
    peVolume: row.peVolume,
  } satisfies StrikeCell),
);

/**
 * A plausible sample max pain — the strike where the sample's CE and PE walls
 * balance. Rendered only behind the sample badge.
 */
export const SAMPLE_MAX_PAIN = SAMPLE_ATM;
