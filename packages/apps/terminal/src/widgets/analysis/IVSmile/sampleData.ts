/**
 * Realistic NIFTY IV smile sample data.
 * Three expiry curves overlaid (current weekly, next weekly, monthly).
 * 21 strikes from 23000 to 25000, step 100.
 * Put IV is systematically higher than Call IV (negative skew / put premium).
 * ATM IV ~14%. 25-delta skew ~+3.5% (puts costlier).
 */

import type { IVSmileData, IVSmileCurveData, IVSmileEntry } from "@/types/api";

const SPOT = 24050;
const ATM = 24000;

const STRIKES = [
  23000, 23100, 23200, 23300, 23400, 23500, 23600, 23700, 23800, 23900,
  24000, 24100, 24200, 24300, 24400, 24500, 24600, 24700, 24800, 24900, 25000,
];

interface CurveConfig {
  expiry: string;
  dte: number;
  atmIV: number;     // decimal (0.14 = 14%)
  smile: number;     // curvature coefficient
  putSkew: number;   // additional IV premium on puts (decimal)
}

const CURVE_CONFIGS: CurveConfig[] = [
  { expiry: "2026-03-27", dte: 3,  atmIV: 0.165, smile: 0.18, putSkew: 0.042 },
  { expiry: "2026-04-03", dte: 10, atmIV: 0.142, smile: 0.14, putSkew: 0.035 },
  { expiry: "2026-04-24", dte: 30, atmIV: 0.128, smile: 0.11, putSkew: 0.028 },
];

function buildCurve(cfg: CurveConfig): IVSmileCurveData {
  const points: IVSmileEntry[] = STRIKES.map((strike) => {
    const moneyness = strike / ATM;                         // call/put moneyness ratio
    const mLog = Math.log(moneyness);                       // log-moneyness
    const smileAdj = cfg.smile * mLog * mLog;               // symmetric curvature

    // Call IV: symmetric smile
    const callIV = Math.max(0.07, cfg.atmIV + smileAdj);

    // Put IV: smile + put skew (downside premium)
    // Skew is proportional to distance below ATM
    const skewAdj = strike < ATM ? cfg.putSkew * (1 - moneyness) * 8 : cfg.putSkew * 0.3;
    const putIV = Math.max(0.08, cfg.atmIV + smileAdj + skewAdj);

    return {
      strike,
      call_iv: parseFloat(callIV.toFixed(4)),
      put_iv: parseFloat(putIV.toFixed(4)),
      moneyness: parseFloat(moneyness.toFixed(5)),
    };
  });

  // ATM IV = midpoint of call and put IV at ATM strike
  const atmPoint = points.find((p) => p.strike === ATM);
  const atmIV = atmPoint
    ? (atmPoint.call_iv + atmPoint.put_iv) / 2
    : cfg.atmIV;

  // 25-delta skew approximation: put IV at 5% OTM minus call IV at 5% OTM
  // (positive = puts costlier = bearish skew, typical for India)
  const otmPut = points.find((p) => p.strike === 22800) ??
    points.find((p) => p.strike === 23000);
  const otmCall = points.find((p) => p.strike === 25200) ??
    points[points.length - 1];
  const skew25d = otmPut && otmCall
    ? parseFloat((otmPut.put_iv - otmCall.call_iv).toFixed(4))
    : parseFloat((cfg.putSkew).toFixed(4));

  return {
    expiry: cfg.expiry,
    days_to_expiry: cfg.dte,
    atm_iv: parseFloat(atmIV.toFixed(4)),
    atm_strike: ATM,
    points,
    skew_25delta: skew25d,
  };
}

export const SAMPLE_IV_SMILE_DATA: IVSmileData = {
  underlying: "NIFTY",
  spot_price: SPOT,
  curves: CURVE_CONFIGS.map(buildCurve),
  is_sample_data: true,
};
