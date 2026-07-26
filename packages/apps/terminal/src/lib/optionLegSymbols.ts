/**
 * optionLegSymbols.ts
 *
 * Resolve an option leg (underlying + leg type, optionally expiry and strike)
 * to a tradable option contract. Extracted from the retired ThreePanel
 * widget's CE/PE resolution so the Chart widget's `optionLeg` panel param —
 * and any future caller — shares one resolution path.
 *
 * Resolution order (ported from ThreePanel):
 *  1. Expiry unspecified → fetch the expiry list and pick the nearest expiry
 *     still in the future on the IST calendar. (ThreePanel took `list[0]`,
 *     trusting the server to sort and prune past expiries; the shared
 *     `selectFutureExpiry` exists precisely because that trust renders stale
 *     contracts, so this helper diverges deliberately — falling back to
 *     `list[0]` only when no entry parses as a future date.)
 *  2. Strike unspecified (or "0", ThreePanel's ATM sentinel) → fetch the
 *     option chain for that expiry and read its ATM strike. ThreePanel fell
 *     back to strike "0" on failure, which silently produced an empty panel;
 *     this helper throws instead so callers can show an honest error.
 *  3. Resolve the contract via the broker resolver (`getOptionSymbol`), with
 *     the compact-symbol builder as the fallback when the resolver fails or
 *     returns nothing — exactly ThreePanel's resolver-then-fallback order,
 *     including passing the absolute strike as the resolver's offset
 *     argument (the convention every existing caller uses).
 */

import { getExpiry, getOptionChain, getOptionSymbol } from "@/services/api";
import { buildCompactOptionSymbol, selectFutureExpiry } from "@/lib/optionSymbols";
import type { OptionType } from "@/lib/optionSymbols";

const DEFAULT_OPTION_EXCHANGE = "NFO";

export interface OptionLegRequest {
  /** Underlying symbol, e.g. "NIFTY". */
  readonly underlying: string;
  /** Option segment exchange; defaults to NFO. */
  readonly exchange?: string;
  /** Which leg to resolve. */
  readonly leg: OptionType;
  /** Expiry label ("31-JUL-25"); nearest future expiry when omitted. */
  readonly expiry?: string;
  /** Absolute strike; ATM (from the option chain) when omitted or "0". */
  readonly strike?: string;
}

export interface ResolvedOptionLeg {
  readonly symbol: string;
  readonly exchange: string;
  readonly strike: string;
  readonly expiry: string;
}

/** Fetch the expiry list and choose the nearest future expiry. */
async function resolveExpiry(underlying: string, exchange: string): Promise<string> {
  let list: string[] = [];
  try {
    const result = await getExpiry(underlying, exchange, "options");
    list = result?.expiry ?? [];
  } catch {
    throw new Error(`Could not load option expiries for ${underlying}`);
  }
  const expiry = selectFutureExpiry(list) ?? list[0];
  if (!expiry) {
    throw new Error(`No option expiries available for ${underlying}`);
  }
  return expiry;
}

/**
 * Fetch the ATM strike from the option chain.
 *
 * The chain payload carries `atm_strike` at runtime (the native normaliser
 * guarantees it; OpenAlgo returns it) even though the typed OptionChainData
 * shape does not declare it — ThreePanel read it through the same cast.
 */
async function resolveATMStrike(
  underlying: string,
  exchange: string,
  expiry: string,
): Promise<string> {
  let atmStrike: number | undefined;
  try {
    const chain = await getOptionChain(underlying, exchange, expiry);
    atmStrike = (chain as unknown as { atm_strike?: number } | null)?.atm_strike;
  } catch {
    throw new Error(`Could not load the option chain for ${underlying} ${expiry}`);
  }
  if (!atmStrike || !Number.isFinite(atmStrike)) {
    throw new Error(`Option chain for ${underlying} ${expiry} carries no ATM strike`);
  }
  return String(atmStrike);
}

/**
 * Resolve an option leg to a tradable contract, filling in the nearest future
 * expiry and the ATM strike when unspecified. Throws with a descriptive
 * message when any step cannot produce a contract.
 */
export async function resolveOptionLeg({
  underlying,
  exchange = DEFAULT_OPTION_EXCHANGE,
  leg,
  expiry,
  strike,
}: OptionLegRequest): Promise<ResolvedOptionLeg> {
  const base = underlying.trim().toUpperCase();
  if (!base) {
    throw new Error("An option leg needs an underlying symbol");
  }

  const legExpiry = expiry?.trim() ? expiry.trim() : await resolveExpiry(base, exchange);
  // ThreePanel treated strike "0" as its ATM sentinel; preserve that.
  const legStrike = strike?.trim() && strike.trim() !== "0"
    ? strike.trim()
    : await resolveATMStrike(base, exchange, legExpiry);

  // Broker resolver first, compact-symbol fallback second — ThreePanel's
  // resolver-then-fallback order, one leg at a time.
  let resolved: { symbol: string; exchange: string } | null = null;
  try {
    const candidate = await getOptionSymbol(base, exchange, legExpiry, leg, legStrike);
    if (candidate?.symbol) {
      resolved = candidate;
    }
  } catch {
    // Resolver unavailable — fall through to the compact builder.
  }
  if (!resolved) {
    const compact = buildCompactOptionSymbol(base, legExpiry, legStrike, leg);
    if (compact) {
      resolved = { symbol: compact, exchange };
    }
  }
  if (!resolved) {
    throw new Error(`Could not resolve the ${base} ${legStrike} ${leg} contract`);
  }

  return {
    symbol: resolved.symbol,
    exchange: resolved.exchange || exchange,
    strike: legStrike,
    expiry: legExpiry,
  };
}
