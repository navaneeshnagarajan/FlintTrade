import { describe, expect, it } from 'vitest';

import { chooseScrollWorldQuality, nextScrollWorldQuality } from './site-scroll-world-quality';

describe('scroll-world quality governor', () => {
  it('caps initial device pixel ratio at 1.5', () => {
    expect(chooseScrollWorldQuality(1)).toEqual({ dpr: 1, emberCount: 180 });
    expect(chooseScrollWorldQuality(2.5)).toEqual({ dpr: 1.5, emberCount: 180 });
  });

  it('lowers DPR before reducing atmosphere when p95 exceeds 20ms', () => {
    expect(nextScrollWorldQuality({ dpr: 1.5, emberCount: 180 }, 21)).toEqual({ dpr: 1.25, emberCount: 180 });
    expect(nextScrollWorldQuality({ dpr: 1.25, emberCount: 180 }, 25)).toEqual({ dpr: 1, emberCount: 180 });
    expect(nextScrollWorldQuality({ dpr: 1, emberCount: 180 }, 25)).toEqual({ dpr: 1, emberCount: 72 });
  });

  it('keeps quality stable when the frame-time budget is met', () => {
    expect(nextScrollWorldQuality({ dpr: 1.5, emberCount: 180 }, 19.9)).toEqual({ dpr: 1.5, emberCount: 180 });
  });

  it('fails open after two slow sample windows at minimum quality', () => {
    const minimum = { dpr: 1, emberCount: 72 };

    expect(nextScrollWorldQuality(minimum, 25, 1)).toEqual(minimum);
    expect(nextScrollWorldQuality(minimum, 25, 2)).toBeNull();
    expect(nextScrollWorldQuality(minimum, 19.9, 3)).toEqual(minimum);
  });
});
