/**
 * useOptionChainData — data fetching and chain transformation hook.
 *
 * Responsibilities:
 *   - Fetch expiries when symbol/exchange changes
 *   - Fetch chain + spot in parallel, auto-refresh at market-aware intervals
 *   - Compute ATM, max OI, PCR, ordered strike rows
 *   - Return all processed data needed by the widget
 */

import { useState, useEffect, useLayoutEffect, useCallback, useMemo, useRef } from "react";
import type { Quote } from "@/types/api";
import { getExpiry, getOptionChain, getQuotes } from "@/services/api";
import { isMarketHours } from "@/lib/market";
import { useMarketDataScope } from "@/hooks/useDataScope";
import { useLatestRequest } from "@/hooks/useLatestRequest";
import type {
  SymbolDef,
  RawOptionChain,
  StrikeRow,
  RawOptionRow,
} from "./types";
import { STRIKES_AROUND_ATM } from "./types";

function optionOI(row: RawOptionRow | null | undefined): number | null {
  const raw = row?.oi ?? row?.open_interest;
  if (typeof raw !== "number" || !Number.isFinite(raw) || !Number.isInteger(raw) || raw < 0) return null;
  return raw;
}

function positiveFiniteNumber(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && value.trim() === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function nonNegativeFiniteNumber(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && value.trim() === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

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
  totalCallOI: number | null;
  totalPutOI: number | null;
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
  const dataScope = useMarketDataScope();
  const [expiries, setExpiries]           = useState<string[]>([]);
  const [selectedExpiryValue, setSelectedExpiry] = useState<string | null>(null);
  const [expiryIdentity, setExpiryIdentity] = useState<string | null>(null);
  const [chain, setChain]                 = useState<RawOptionChain | null>(null);
  const [chainIdentity, setChainIdentity] = useState<string | null>(null);
  const [spot, setSpot]                   = useState<Quote | null>(null);
  const [spotIdentity, setSpotIdentity]   = useState<string | null>(null);
  const [loading, setLoading]             = useState(false);
  const [error, setError]                 = useState<string | null>(null);
  const [lastRefresh, setLastRefresh]     = useState<Date | null>(null);
  const identityKey = `${dataScope}:${symDef.label}:${exchange}`;
  const currentExpiries = expiryIdentity === identityKey ? expiries : [];
  const expiryCandidate = typeof selectedExpiryValue === "string" ? selectedExpiryValue.trim() : "";
  const selectedExpiry = currentExpiries.includes(expiryCandidate) ? expiryCandidate : null;
  const requestKey = `${identityKey}:${selectedExpiry ?? ""}`;
  // State setters retire in passive effects, but render-time identity tagging
  // prevents even the first paint under authority B from exposing A's values.
  const currentChain = chainIdentity === requestKey ? chain : null;
  const currentSpot = spotIdentity === requestKey ? spot : null;
  // Shared guard: identity changes invalidate every in-flight response and a
  // pending request for the same key makes the next poll tick a no-op.
  const requests = useLatestRequest(requestKey);
  const requestControllerRef = useRef<AbortController | null>(null);

  useLayoutEffect(() => {
    setChain(null);
    setChainIdentity(null);
    setSpot(null);
    setSpotIdentity(null);
    setLoading(false);
    setError(null);
    setLastRefresh(null);
  }, [requestKey]);

  useEffect(() => () => {
    requestControllerRef.current?.abort();
    requestControllerRef.current = null;
    requests.invalidate();
  }, [requestKey, requests]);

  // Fetch expiries when symbol/exchange changes
  useEffect(() => {
    setExpiries([]);
    setSelectedExpiry(null);
    setExpiryIdentity(null);
    setChain(null);
    setError(null);

    const controller = new AbortController();
    (async () => {
      try {
        const data = await getExpiry(
          symDef.label,
          exchange,
          "options",
          controller.signal,
          dataScope,
        );
        if (controller.signal.aborted) return;
        const rawList = Array.isArray(data)
          ? data
          : ((data as { expiry?: unknown[] })?.expiry ?? []);
        const list = rawList.flatMap((value) => {
          if (typeof value !== "string") return [];
          const expiry = value.trim();
          return expiry ? [expiry] : [];
        });
        setExpiries(list);
        setExpiryIdentity(identityKey);
        setSelectedExpiry(list[0] ?? null);
      } catch (e) {
        if (!controller.signal.aborted) setError(`Failed to load expiries: ${(e as Error).message}`);
      }
    })();
    return () => controller.abort();
   
  }, [identityKey, symDef.label, exchange, dataScope]);

  const fetchData = useCallback(async () => {
    if (!selectedExpiry) return;

    const ticket = requests.begin(requestKey);
    if (!ticket) return;
    const controller = new AbortController();
    requestControllerRef.current = controller;
    setLoading(true);
    setError(null);

    try {
      const [chainResult, spotResult] = await Promise.allSettled([
        getOptionChain(symDef.label, exchange, selectedExpiry, controller.signal, dataScope),
        getQuotes(symDef.spotSymbol, symDef.spotExchange, controller.signal, dataScope),
      ]);

      if (!ticket.isCurrent()) return;

      if (chainResult.status === "fulfilled") {
        setChain(chainResult.value as unknown as RawOptionChain);
        setChainIdentity(requestKey);
        setError(null);
      } else {
        setChain(null);
        setChainIdentity(requestKey);
        setError(`Chain error: ${(chainResult.reason as Error)?.message}`);
      }

      if (spotResult.status === "fulfilled") {
        setSpot(spotResult.value);
        setSpotIdentity(requestKey);
      } else {
        setSpot(null);
        setSpotIdentity(requestKey);
      }
    } finally {
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
      }
      if (ticket.settle()) {
        setLoading(false);
        setLastRefresh(new Date());
      }
    }
   
  }, [
    dataScope,
    requests,
    requestKey,
    selectedExpiry,
    symDef.label,
    symDef.spotSymbol,
    symDef.spotExchange,
    exchange,
  ]);

  // Auto-refresh at market-aware intervals
  useEffect(() => {
    if (!selectedExpiry) return;
    void fetchData();
    const interval = isMarketHours() ? 3000 : 30000;
    const id = setInterval(() => void fetchData(), interval);
    return () => clearInterval(id);
  }, [fetchData, selectedExpiry]);

  // Compute ordered strike list, ATM, max OI, PCR
  const { strikes, atmStrike, maxCallOI, maxPutOI, totalCallOI, totalPutOI, computedPCR } = useMemo(() => {
    if (!currentChain) return {
      strikes: [] as StrikeRow[],
      atmStrike: null as number | null,
      maxCallOI: 0,
      maxPutOI: 0,
      totalCallOI: null as number | null,
      totalPutOI: null as number | null,
      computedPCR: null as number | null,
    };

    const callMap: Record<number, RawOptionRow> = {};
    const putMap:  Record<number, RawOptionRow> = {};

    if (currentChain.chain && currentChain.chain.length > 0) {
      // OpenAlgo v2 format: chain[].strike, chain[].ce, chain[].pe
      for (const entry of currentChain.chain) {
        const strike = positiveFiniteNumber(entry.strike);
        if (strike === null) continue;
        if (entry.ce) callMap[strike] = { ...entry.ce, strike };
        if (entry.pe) putMap[strike] = { ...entry.pe, strike };
      }
    } else {
      // Legacy v1 format: separate calls[] and puts[] arrays
      for (const call of currentChain.calls ?? []) {
        const strike = positiveFiniteNumber(call.strike_price ?? call.strike);
        if (strike !== null) callMap[strike] = call;
      }
      for (const put of currentChain.puts ?? []) {
        const strike = positiveFiniteNumber(put.strike_price ?? put.strike);
        if (strike !== null) putMap[strike] = put;
      }
    }

    const allStrikes = Array.from(
      new Set([
        ...Object.keys(callMap).map(Number),
        ...Object.keys(putMap).map(Number),
      ])
    ).sort((a, b) => a - b);

    const spotLtp = positiveFiniteNumber(currentSpot?.ltp)
      ?? positiveFiniteNumber(currentChain.underlying_ltp);
    const atm = spotLtp !== null && allStrikes.length > 0
      ? allStrikes.reduce((prev, cur) => (
          Math.abs(cur - spotLtp) < Math.abs(prev - spotLtp) ? cur : prev
        ))
      : null;

    const atmIdx = allStrikes.indexOf(atm ?? 0);
    const lo = Math.max(0, atmIdx - STRIKES_AROUND_ATM);
    const hi = Math.min(allStrikes.length - 1, atmIdx + STRIKES_AROUND_ATM);
    const visible = allStrikes.slice(lo, hi + 1);

    const callOi = visible.map((strike) => optionOI(callMap[strike]));
    const putOi = visible.map((strike) => optionOI(putMap[strike]));
    const knownCallOi = callOi.filter((oi): oi is number => oi !== null);
    const knownPutOi = putOi.filter((oi): oi is number => oi !== null);
    const hasCompleteCallOi = visible.length > 0 && callOi.every((oi) => oi !== null);
    const hasCompletePutOi = visible.length > 0 && putOi.every((oi) => oi !== null);
    const maxCallOI = hasCompleteCallOi ? Math.max(0, ...knownCallOi) : 0;
    const maxPutOI = hasCompletePutOi ? Math.max(0, ...knownPutOi) : 0;
    const totalCallOI = hasCompleteCallOi ? callOi.reduce((total, oi) => total + oi!, 0) : null;
    const totalPutOI = hasCompletePutOi ? putOi.reduce((total, oi) => total + oi!, 0) : null;
    const computedPCR = totalCallOI !== null && totalPutOI !== null && totalCallOI > 0
      ? totalPutOI / totalCallOI
      : null;

    return {
      strikes: visible.map((s) => ({ strike: s, call: callMap[s] ?? null, put: putMap[s] ?? null })),
      atmStrike: atm,
      maxCallOI,
      maxPutOI,
      totalCallOI,
      totalPutOI,
      computedPCR,
    };
  }, [currentChain, currentSpot]);

  // Spot display values
  const spotLtp       = positiveFiniteNumber(currentSpot?.ltp);
  const spotPrevClose = positiveFiniteNumber(
    (currentSpot as unknown as { prev_close?: number })?.prev_close ?? currentSpot?.close,
  );
  const spotChange    = spotLtp !== null && spotPrevClose !== null ? spotLtp - spotPrevClose : null;
  const spotChangePct = spotChange !== null && spotPrevClose !== null
    ? (spotChange / spotPrevClose) * 100
    : null;
  const spotUp        = spotChange == null ? null : spotChange >= 0;
  const responsePCR   = nonNegativeFiniteNumber(currentChain?.pcr);
  const pcr           = totalCallOI !== null && totalCallOI > 0 && totalPutOI !== null
    ? responsePCR ?? computedPCR
    : null;

  return {
    expiries: currentExpiries,
    selectedExpiry,
    setSelectedExpiry,
    chain: currentChain,
    spot: currentSpot,
    loading,
    error,
    lastRefresh,
    fetchData,
    strikes,
    atmStrike,
    maxCallOI,
    maxPutOI,
    totalCallOI,
    totalPutOI,
    computedPCR,
    spotLtp,
    spotChange,
    spotChangePct,
    spotUp,
    pcr,
  };
}
