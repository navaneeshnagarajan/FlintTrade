/**
 * Sample Greeks surface data for explore/disconnected mode.
 * NIFTY options — 3 expiries × 11 moneyness buckets (-5% to +5%).
 * IV surface with realistic smile shape and term structure.
 */

export interface GreeksSurfacePoint {
  /** Moneyness bucket label, e.g. "-5%", "ATM", "+3%". */
  moneyness: string;
  /** Moneyness as decimal offset from ATM, e.g. -0.05, 0, +0.03. */
  moneynessVal: number;
  /** Strike price. */
  strike: number;
  /** Implied volatility (%) */
  iv: number;
  /** Black-Scholes delta (call delta, 0–1). */
  delta: number;
  /** Black-Scholes gamma (per rupee). */
  gamma: number;
  /** Black-Scholes theta (per day, negative). */
  theta: number;
}

export interface GreeksSurfaceExpiry {
  expiry: string;
  label: string;
  dte: number;
  points: GreeksSurfacePoint[];
}

// ATM spot for sample data
const SPOT = 24050;
const ATM_STRIKE = 24000;

const MONEYNESS_STEPS = [-0.05, -0.04, -0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03, 0.04, 0.05];
const MONEYNESS_LABELS = ["-5%", "-4%", "-3%", "-2%", "-1%", "ATM", "+1%", "+2%", "+3%", "+4%", "+5%"];

interface ExpiryCfg {
  expiry: string;
  label: string;
  dte: number;
  atmIV: number;
  smileCurve: number;
  putSkew: number;
}

const EXPIRY_CFGS: ExpiryCfg[] = [
  { expiry: "2026-04-10", label: "Front Week", dte: 1,  atmIV: 18.2, smileCurve: 3.8, putSkew: 2.1 },
  { expiry: "2026-04-24", label: "Front Month", dte: 15, atmIV: 14.6, smileCurve: 2.6, putSkew: 1.5 },
  { expiry: "2026-05-29", label: "Back Month",  dte: 50, atmIV: 13.1, smileCurve: 1.9, putSkew: 1.1 },
];

function bsApproxDelta(moneyVal: number, dte: number, iv: number): number {
  // Very rough approximation: N(d1) with simplified d1
  const T = dte / 365;
  if (T <= 0) return moneyVal >= 0 ? 1 : 0;
  const ivDec = iv / 100;
  const d1 = (-moneyVal + 0.5 * ivDec * ivDec * T) / (ivDec * Math.sqrt(T));
  // Approximate N(d1) with a fast sigmoid
  return 1 / (1 + Math.exp(-1.7 * d1));
}

function bsApproxGamma(moneyVal: number, dte: number, iv: number, strike: number): number {
  const T = dte / 365;
  if (T <= 0) return 0;
  const ivDec = iv / 100;
  const d1 = (-moneyVal + 0.5 * ivDec * ivDec * T) / (ivDec * Math.sqrt(T));
  const pdf = Math.exp(-0.5 * d1 * d1) / Math.sqrt(2 * Math.PI);
  return pdf / (strike * ivDec * Math.sqrt(T));
}

function buildExpiry(cfg: ExpiryCfg): GreeksSurfaceExpiry {
  const points: GreeksSurfacePoint[] = MONEYNESS_STEPS.map((mv, idx) => {
    const strike = Math.round(ATM_STRIKE * (1 + mv) / 50) * 50;
    const mLog = Math.log(1 + mv);
    // Symmetric smile curvature
    const smileAdj = cfg.smileCurve * mLog * mLog;
    // Put skew: OTM puts get extra premium
    const skewAdj = mv < 0 ? cfg.putSkew * Math.abs(mv) * 10 : cfg.putSkew * 0.2 * mv * 10;
    const iv = Math.max(8, cfg.atmIV + smileAdj + skewAdj);
    const delta = bsApproxDelta(mv, cfg.dte, iv);
    const gamma = bsApproxGamma(mv, cfg.dte, iv, strike);
    // Theta: at-the-money theta is highest (time value erosion)
    const thetaBase = -(iv / 100) * SPOT * Math.exp(-0.5 * mv * mv * 100) / Math.sqrt(365 * Math.max(1, cfg.dte) * 2 * Math.PI);
    return {
      moneyness: MONEYNESS_LABELS[idx],
      moneynessVal: mv,
      strike,
      iv: parseFloat(iv.toFixed(2)),
      delta: parseFloat(delta.toFixed(4)),
      gamma: parseFloat((gamma * 1000).toFixed(6)), // per 1000 notional
      theta: parseFloat(thetaBase.toFixed(2)),
    };
  });

  return { expiry: cfg.expiry, label: cfg.label, dte: cfg.dte, points };
}

export const SAMPLE_GREEKS_SURFACE_DATA: GreeksSurfaceExpiry[] = EXPIRY_CFGS.map(buildExpiry);
