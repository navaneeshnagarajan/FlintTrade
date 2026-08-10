/** Small deterministic quality governor for the optional WebGL enhancement. */

export interface ScrollWorldQuality {
  dpr: number;
  emberCount: number;
}

const MAX_DPR = 1.5;
const MIN_DPR = 1;
const FULL_EMBERS = 180;
const REDUCED_EMBERS = 72;
const FRAME_BUDGET_MS = 20;

export function chooseScrollWorldQuality(devicePixelRatio: number): ScrollWorldQuality {
  return {
    dpr: Math.max(MIN_DPR, Math.min(devicePixelRatio || MIN_DPR, MAX_DPR)),
    emberCount: FULL_EMBERS,
  };
}

export function nextScrollWorldQuality(
  current: ScrollWorldQuality,
  p95FrameTimeMs: number,
): ScrollWorldQuality {
  if (p95FrameTimeMs <= FRAME_BUDGET_MS) return current;
  if (current.dpr > MIN_DPR) {
    return { ...current, dpr: Math.max(MIN_DPR, current.dpr - 0.25) };
  }
  if (current.emberCount > REDUCED_EMBERS) {
    return { ...current, emberCount: REDUCED_EMBERS };
  }
  return current;
}
