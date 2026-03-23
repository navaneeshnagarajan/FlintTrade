/**
 * useOptionChainData — data fetching and chain transformation hook.
 *
 * Responsibilities:
 *   - Fetch expiries when symbol/exchange changes
 *   - Fetch chain + spot in parallel, auto-refresh at market-aware intervals
 *   - Compute ATM, max OI, PCR, ordered strike rows
 *   - Return all processed data needed by the widget
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import type { Quote } from "@/types/api";
import { getExpiry, getOptionChain, getQuotes } from "@/services/api";
import { isMarketHours } from "@/lib/market";
import type {
  SymbolDef,
  RawOptionChain,
  StrikeRow,
  RawOptionRow,
} from "./types";
import { STRIKES_AROUND_ATM } from "./types";

export interface OptionChainData {
  // Expiry
  expiries: string[];
  selectedExpiry: string | null;
  setSelectedExpiry: (v: string | null) => void;

  // Chain + spot
  chain: RawOptionChain | null;
  spot: Quote | null;

  // Fetch state
  loading: boolean;
  error: string | null;
  lastRefresh: Date | null;
  fetchData: () => void;

  // Derived
  strikes: StrikeRow[];
  atmStrike: number | null;
  maxCallOI: number;
  maxPutOI: number;
  computedPCR: number | null;

  // Spot display values
  spotLtp: number | null;
  spotChange: number | null;
  spotChangePct: number | null;
  spotUp: boolean | null;

  // PCR — API value preferred, computed fallback
  pcr: number | null;
}

export function useOptionChainData(
  symDef: SymbolDef,
  exchange: string,
): OptionChainData {
  const [expiries, setExpiries]           = useState<string[]>([]);
  const [selectedExpiry, setSelectedExpiry] = useState<string | null>(null);
  const [chain, setChain]                 = useState<RawOptionChain | null>(null);
  const [spot, setSpot]                   = useState<Quote | null>(null);
  const [loading, setLoading]             = useState(false);
  const [error, setError]                 = useState<string | null>(null);
  const [lastRefresh, setLastRefresh]     = useState<Date | null>(null);

  // Fetch expiries when symbol/exchange changes
  useEffect(() => {
    setExpiries([]);
    setSelectedExpiry(null);
    setChain(null);
    setError(null);

    let cancelled = false;
    (async () => {
      try {
        const data = await getExpiry(symDef.label, exchange);
        if (cancelled) return;
        const list = Array.isArray(data)
          ? (data as string[])
          : ((data as { expiry?: string[] })?.expiry ?? []);
        setExpiries(list);
        if (list.length > 0) setSelectedExpiry(list[0]);
      } catch (e) {
        if (!cancelled) setError(`Failed to load expiries: ${(e as Error).message}`);
      }
    })();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symDef.label, exchange]);

  const fetchData = useCallback(async () => {
    if (!selectedExpiry || expiries.length === 0) return;
    if (!expiries.includes(selectedExpiry)) return;

    const fetchKey = `${symDef.label}:${exchange}`;
    setLoading(true);
    setError(null);

    try {
      const [chainResult, spotResult] = await Promise.allSettled([
        getOptionChain(symDef.label, exchange, selectedExpiry),
        getQuotes(symDef.spotSymbol, symDef.spotExchange),
      ]);

      if (fetchKey !== `${symDef.label}:${exchange}`) return;

      if (chainResult.status === "fulfilled") {
        setChain(chainResult.value as unknown as RawOptionChain);
        setError(null);
      } else {
        setError(`Chain error: ${(chainResult.reason as Error)?.message}`);
      }

      if (spotResult.status === "fulfilled") {
        setSpot(spotResult.value);
      }
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedExpiry, symDef.label, symDef.spotSymbol, symDef.spotExchange, exchange, expiries]);

  // Auto-refresh at market-aware intervals
  useEffect(() => {
    void fetchData();
    const interval = isMarketHours() ? 3000 : 30000;
    const id = setInterval(() => void fetchData(), interval);
    return () => clearInterval(id);
  }, [fetchData]);

  // Compute ordered strike list, ATM, max OI, PCR
  const { strikes, atmStrike, maxCallOI, maxPutOI, computedPCR } = useMemo(() => {
    if (!chain) return {
      strikes: [] as StrikeRow[],
      atmStrike: null as number | null,
      maxCallOI: 0,
      maxPutOI: 0,
      computedPCR: null as number | null,
    };

    const callMap: Record<number, RawOptionRow> = {};
    const putMap:  Record<number, RawOptionRow> = {};

    if (chain.chain && chain.chain.length > 0) {
      // OpenAlgo v2 format: chain[].strike, chain[].ce, chain[].pe
      for (const entry of chain.chain) {
        if (entry.ce) callMap[entry.strike] = { ...entry.ce, strike: entry.strike };
        if (entry.pe) putMap[entry.strike]  = { ...entry.pe, strike: entry.strike };
      }
    } else {
      // Legacy v1 format: separate calls[] and puts[] arrays
      (chain.calls ?? []).forEach((c) => { callMap[c.strike_price ?? c.strike ?? 0] = c; });
      (chain.puts  ?? []).forEach((p) => { putMap[p.strike_price  ?? p.strike  ?? 0] = p; });
    }

    const allStrikes = Array.from(
      new Set([
        ...Object.keys(callMap).map(Number),
        ...Object.keys(putMap).map(Number),
      ])
    ).sort((a, b) => a - b);

    const spotLtp = spot?.ltp ?? null;
    const atm = chain.atm_strike ?? (spotLtp
      ? allStrikes.reduce((prev, cur) =>
          Math.abs(cur - spotLtp) < Math.abs(prev - spotLtp) ? cur : prev,
          allStrikes[0] ?? 0)
      : allStrikes[Math.floor(allStrikes.length / 2)] ?? null);

    const atmIdx = allStrikes.indexOf(atm ?? 0);
    const lo = Math.max(0, atmIdx - STRIKES_AROUND_ATM);
    const hi = Math.min(allStrikes.length - 1, atmIdx + STRIKES_AROUND_ATM);
    const visible = allStrikes.slice(lo, hi + 1);

    const maxCallOI = Math.max(0, ...visible.map((s) => Number(callMap[s]?.oi ?? callMap[s]?.open_interest ?? 0)));
    const maxPutOI  = Math.max(0, ...visible.map((s) => Number(putMap[s]?.oi  ?? putMap[s]?.open_interest  ?? 0)));

    const totalCallOI = visible.reduce((acc, s) => acc + Number(callMap[s]?.oi ?? callMap[s]?.open_interest ?? 0), 0);
    const totalPutOI  = visible.reduce((acc, s) => acc + Number(putMap[s]?.oi  ?? putMap[s]?.open_interest  ?? 0), 0);
    const computedPCR = totalCallOI > 0 ? totalPutOI / totalCallOI : null;

    return {
      strikes: visible.map((s) => ({ strike: s, call: callMap[s] ?? null, put: putMap[s] ?? null })),
      atmStrike: atm,
      maxCallOI,
      maxPutOI,
      computedPCR,
    };
  }, [chain, spot]);

  // Spot display values
  const spotLtp       = spot?.ltp ?? null;
  const spotPrevClose = (spot as unknown as { prev_close?: number })?.prev_close ?? spot?.close ?? null;
  const spotChange    = spotLtp && spotPrevClose ? spotLtp - spotPrevClose : null;
  const spotChangePct = spotChange && spotPrevClose ? (spotChange / spotPrevClose) * 100 : null;
  const spotUp        = spotChange == null ? null : spotChange >= 0;
  const pcr           = chain?.pcr != null ? chain.pcr : computedPCR;

  return {
    expiries,
    selectedExpiry,
    setSelectedExpiry,
    chain,
    spot,
    loading,
    error,
    lastRefresh,
    fetchData,
    strikes,
    atmStrike,
    maxCallOI,
    maxPutOI,
    computedPCR,
    spotLtp,
    spotChange,
    spotChangePct,
    spotUp,
    pcr,
  };
}
