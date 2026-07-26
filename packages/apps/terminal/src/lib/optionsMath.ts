/**
 * optionsMath — the single client-side Black–Scholes module for the terminal.
 *
 * Before this module four separate widget-local copies of "Black–Scholes"
 * existed (GreeksSurface's live hook and its sample generator, GreeksHeatmap's
 * transform, and GreeksHeatmap's ad-hoc sample rows). Every one of them
 * approximated N(d1) with a logistic `1 / (1 + exp(-1.7·d1))` — a sigmoid whose
 * error against the true normal CDF exceeds 1 delta point around ±1σ — and each
 * was pinned by its own tests, so they were free to drift apart. This module is
 * the single source; the copies are gone.
 *
 * SERVER-SIDE NOTE: a correct Black–Scholes implementation already exists in
 * `packages/services/screener/src/flinttrade_screener/greeks.py` (`_bs_greeks`
 * at :257, `_norm_cdf` at :301), but it is NOT exposed to the terminal by any
 * route — the IV-smile payload carries volatility only, never greeks. The
 * long-term fix is to expose that server implementation over `/api/v1` so the
 * terminal renders broker/backend-derived greeks instead of deriving its own.
 * Until that route exists, this module is the interim single source of truth,
 * and anything it returns is a *client-side derivation*, not broker data.
 *
 * ## Conventions (deliberate, and relied upon by the widgets)
 *
 * - **Option type** — `"call"` or `"put"`. Both option-chain widgets currently
 *   render call-side greeks.
 * - **Rate** — defaults to `0`. The IV-smile payload the widgets derive from
 *   carries no rate, so every pre-existing call site was implicitly a zero-rate
 *   derivation; defaulting to 0 keeps rendered deltas honest rather than
 *   silently shifting them by an assumed Indian risk-free rate. Callers that do
 *   know the rate should pass it (the server-side `_bs_greeks` defaults 0.07).
 * - **Delta** — unscaled, `N(d1)` for a call and `N(d1) − 1` for a put, so
 *   `delta_call − delta_put = 1` (put–call parity) holds exactly.
 * - **Gamma** — scaled ×1000, i.e. `φ(d1) / (S·σ·√T) × 1000`. Raw index gamma
 *   is of order 1e-4 (NIFTY at 22,000) and rounds to "0.0000" in the widgets'
 *   4-decimal cells; the ×1000 scaling is what both existing widgets already
 *   rendered. Read it as gamma per 1,000 units of the underlying.
 * - **Theta** — per calendar DAY (the annualised figure ÷ 365), negative for a
 *   long option. This matches what the widgets label "/d".
 * - **Vega** — per 1 percentage-point IV move, `S·φ(d1)·√T / 100`, matching the
 *   server-side convention in `greeks.py:290`.
 * - **Rho** — per 1 percentage-point rate move.
 * - **Degenerate input** — non-finite input, or a non-positive spot, strike,
 *   time or volatility, returns ALL-ZERO greeks (delta included). At or past
 *   expiry there is no time value, so a lone non-zero delta inside a grid
 *   labelled "Live" would read as meaningful when it is not; reporting the whole
 *   point inert is the fail-closed choice.
 *
 * Nothing here rounds: call sites keep their own display rounding.
 */

/** 1 / √(2π), the standard normal PDF's normalising constant. */
const INV_SQRT_2PI = 0.3989422804014327;

/** Calendar days per year — the terminal's DTE→years and theta/day divisor. */
export const DAYS_PER_YEAR = 365;

/** Gamma display scaling: gamma is reported per 1,000 units of the underlying. */
export const GAMMA_SCALE = 1000;

/**
 * IV values above this are read as percentage points (14.8) rather than a
 * decimal fraction (0.148). No traded instrument sustains a 150% decimal IV, so
 * the threshold is unambiguous in practice.
 */
const IV_PERCENT_THRESHOLD = 1.5;

/** Abramowitz–Stegun 26.2.17 coefficients — absolute error < 7.5 × 10⁻⁸. */
const AS_P = 0.2316419;
const AS_B1 = 0.319381530;
const AS_B2 = -0.356563782;
const AS_B3 = 1.781477937;
const AS_B4 = -1.821255978;
const AS_B5 = 1.330274429;

/** Which side of the contract the greeks are for. */
export type OptionType = "call" | "put";

/** Inputs to a single Black–Scholes greeks evaluation. */
export interface BsGreeksInput {
  /** Underlying spot (or the ATM strike used as a spot proxy), > 0. */
  spot: number;
  /** Contract strike, > 0. */
  strike: number;
  /** Time to expiry in YEARS (use `yearsFromDays` for a DTE figure), > 0. */
  timeToExpiryYears: number;
  /** Implied volatility as a DECIMAL fraction (0.15 = 15%), > 0. */
  volatility: number;
  /** Annualised risk-free rate as a decimal fraction. Defaults to 0. */
  rate?: number;
  /** Contract side. */
  optionType: OptionType;
}

/** Black–Scholes greeks in this module's documented conventions. */
export interface BsGreeks {
  /** N(d1) for a call, N(d1) − 1 for a put. Unscaled. */
  delta: number;
  /** φ(d1) / (S·σ·√T), scaled ×1000 (per 1,000 units of underlying). */
  gamma: number;
  /** Per calendar day (annualised ÷ 365); negative for a long option. */
  theta: number;
  /** Per 1 percentage-point IV move. */
  vega: number;
  /** Per 1 percentage-point rate move. */
  rho: number;
}

/** All-zero greeks — the fail-inert result for degenerate input. */
function inertGreeks(): BsGreeks {
  return { delta: 0, gamma: 0, theta: 0, vega: 0, rho: 0 };
}

/**
 * Standard normal probability density function, φ(x).
 *
 * @param x Standardised value.
 * @returns The density at `x`; 0 for non-finite input.
 */
export function normPdf(x: number): number {
  if (!Number.isFinite(x)) return 0;
  return INV_SQRT_2PI * Math.exp(-0.5 * x * x);
}

/**
 * Standard normal cumulative distribution function, N(x).
 *
 * Uses the Abramowitz–Stegun 26.2.17 rational approximation (absolute error
 * below 7.5 × 10⁻⁸ across the whole real line) — NOT the logistic
 * `1 / (1 + exp(-1.7x))` sigmoid the widgets used before this module, which is
 * off by more than a delta point around ±1σ.
 *
 * @param x Standardised value.
 * @returns P(Z ≤ x) in [0, 1]. −∞ yields 0, +∞ yields 1, NaN yields 0.
 */
export function normCdf(x: number): number {
  if (Number.isNaN(x)) return 0;
  if (x === Number.POSITIVE_INFINITY) return 1;
  if (x === Number.NEGATIVE_INFINITY) return 0;

  const absX = Math.abs(x);
  const t = 1 / (1 + AS_P * absX);
  const poly = t * (AS_B1 + t * (AS_B2 + t * (AS_B3 + t * (AS_B4 + t * AS_B5))));
  // The approximation gives the UPPER tail P(Z > |x|); mirror it for x < 0.
  const upperTail = normPdf(absX) * poly;
  return x >= 0 ? 1 - upperTail : upperTail;
}

/**
 * Convert a days-to-expiry figure to the year fraction Black–Scholes expects.
 *
 * @param days Calendar days to expiry.
 * @returns `days / 365`, or 0 when `days` is non-finite or non-positive.
 */
export function yearsFromDays(days: number): number {
  if (!Number.isFinite(days) || days <= 0) return 0;
  return days / DAYS_PER_YEAR;
}

/**
 * Black–Scholes d1 = (ln(S/K) + (r + σ²/2)·T) / (σ·√T).
 *
 * @param spot Underlying spot, > 0.
 * @param strike Contract strike, > 0.
 * @param timeToExpiryYears Time to expiry in years, > 0.
 * @param volatility Implied volatility as a decimal fraction, > 0.
 * @param rate Annualised risk-free rate as a decimal fraction. Defaults to 0.
 * @returns d1, or NaN when any input is degenerate.
 */
export function d1(
  spot: number,
  strike: number,
  timeToExpiryYears: number,
  volatility: number,
  rate: number = 0,
): number {
  if (!(spot > 0) || !(strike > 0) || !(timeToExpiryYears > 0) || !(volatility > 0)) {
    return Number.NaN;
  }
  if (!Number.isFinite(rate)) return Number.NaN;
  const sigmaSqrtT = volatility * Math.sqrt(timeToExpiryYears);
  return (
    (Math.log(spot / strike) + (rate + 0.5 * volatility * volatility) * timeToExpiryYears)
    / sigmaSqrtT
  );
}

/**
 * Black–Scholes d2 = d1 − σ·√T.
 *
 * @param spot Underlying spot, > 0.
 * @param strike Contract strike, > 0.
 * @param timeToExpiryYears Time to expiry in years, > 0.
 * @param volatility Implied volatility as a decimal fraction, > 0.
 * @param rate Annualised risk-free rate as a decimal fraction. Defaults to 0.
 * @returns d2, or NaN when any input is degenerate.
 */
export function d2(
  spot: number,
  strike: number,
  timeToExpiryYears: number,
  volatility: number,
  rate: number = 0,
): number {
  return d1(spot, strike, timeToExpiryYears, volatility, rate)
    - volatility * Math.sqrt(timeToExpiryYears);
}

/**
 * Full Black–Scholes greeks for one European option.
 *
 * See the module docstring for the sign and scale conventions — in particular
 * gamma is scaled ×1000, theta is per calendar day, and vega/rho are per
 * percentage point. Degenerate input returns all-zero greeks.
 *
 * @param input Contract and market parameters.
 * @returns Delta, gamma, theta, vega and rho, unrounded.
 */
export function bsGreeks(input: BsGreeksInput): BsGreeks {
  const { spot, strike, timeToExpiryYears, volatility, optionType } = input;
  const rate = input.rate ?? 0;

  if (![spot, strike, timeToExpiryYears, volatility, rate].every((v) => Number.isFinite(v))) {
    return inertGreeks();
  }
  if (!(spot > 0) || !(strike > 0) || !(timeToExpiryYears > 0) || !(volatility > 0)) {
    return inertGreeks();
  }

  const sqrtT = Math.sqrt(timeToExpiryYears);
  const dOne = d1(spot, strike, timeToExpiryYears, volatility, rate);
  const dTwo = dOne - volatility * sqrtT;
  const pdfD1 = normPdf(dOne);
  const discount = Math.exp(-rate * timeToExpiryYears);
  const isCall = optionType === "call";

  // Shared time-decay term: −S·φ(d1)·σ / (2·√T), annualised.
  const decay = -(spot * pdfD1 * volatility) / (2 * sqrtT);
  const carry = rate * strike * discount;

  const delta = isCall ? normCdf(dOne) : normCdf(dOne) - 1;
  const gamma = (pdfD1 / (spot * volatility * sqrtT)) * GAMMA_SCALE;
  const thetaAnnual = isCall
    ? decay - carry * normCdf(dTwo)
    : decay + carry * normCdf(-dTwo);

  return {
    delta,
    gamma,
    theta: thetaAnnual / DAYS_PER_YEAR,
    vega: (spot * pdfD1 * sqrtT) / 100,
    rho: isCall
      ? (strike * timeToExpiryYears * discount * normCdf(dTwo)) / 100
      : -(strike * timeToExpiryYears * discount * normCdf(-dTwo)) / 100,
  };
}

/**
 * Normalise an implied-volatility figure to a 0–1 decimal fraction.
 *
 * The current screener endpoint reports decimal IV; percentage-point
 * normalisation is retained only for one-way compatibility with older
 * saved/mock payloads that reported 14.8 for 14.8%.
 *
 * @param value Raw IV, either a decimal fraction or percentage points.
 * @returns The IV as a decimal fraction, or 0 when non-finite or non-positive.
 */
export function normaliseIv(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 0;
  return value > IV_PERCENT_THRESHOLD ? value / 100 : value;
}
