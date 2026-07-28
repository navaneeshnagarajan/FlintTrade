// Server-computed indicator data hook.
//
// The design-system registry declares the server tier's toggles, panes and
// series specs like any client indicator; this hook supplies their DATA by
// posting the chart's bars to POST /api/v1/indicators/compute (the
// flinttrade_indicators NumPy engine — restored to the chart in the
// indicator-wiring wave after sitting caller-less since 2026-06-09).
// Fetches are sequenced: a stale response never overwrites a newer one.

import { useCallback, useEffect, useRef, useState } from "react";
import type { FlintChartOhlcvBar as OhlcvBar } from "@flinttrade/design-system";
import { computeIndicators } from "@/services/ftApi.analysis";
import type { IndicatorComputeSeries } from "@/services/ftApi.analysis";
import type { IndicatorState, IndicatorPeriods } from "./types";

/** Chart toggles served by the backend, with their request-name builders. */
const SERVER_INDICATOR_KEYS = [
  "showKAMA",
  "showALMA",
  "showDonchian",
  "showChandelier",
  "showStochRSI",
  "showMFI",
  "showSqueeze",
  "showAO",
  "showTEMA",
  "showT3",
  "showTRIMA",
  "showMcGinley",
  "showMAEnvelopes",
  "showSTARC",
  "showCMF",
  "showROC",
  "showMomentum",
  "showTRIX",
  "showChop",
  "showHV",
  "showVortex",
  "showFisher",
  "showKST",
  "showCoppock",
  "showAD",
  "showPVT",
] as const;

export type ServerIndicatorKey = (typeof SERVER_INDICATOR_KEYS)[number];

export type ServerIndicatorData = Record<string, IndicatorComputeSeries>;

/** The compute-route request name for a server-tier toggle. */
export function serverIndicatorName(key: ServerIndicatorKey, periods: IndicatorPeriods): string {
  switch (key) {
    case "showKAMA": return `kama_${periods.kama}`;
    case "showALMA": return `alma_${periods.alma}`;
    case "showDonchian": return `donchian_channels_${periods.donchian}`;
    case "showChandelier": return `chandelier_exit_${periods.chand}`;
    case "showStochRSI": return `stoch_rsi_${periods.stochRsi}`;
    case "showMFI": return `mfi_${periods.mfi}`;
    case "showSqueeze": return "squeeze_momentum";
    case "showAO": return "awesome_oscillator";
    case "showTEMA": return `tema_${periods.tema}`;
    case "showT3": return `t3_${periods.t3}`;
    case "showTRIMA": return `trima_${periods.trima}`;
    case "showMcGinley": return `mcginley_dynamic_${periods.mcginley}`;
    case "showMAEnvelopes": return `moving_average_envelopes_${periods.mae}`;
    case "showSTARC": return "starc_bands";
    case "showCMF": return `cmf_${periods.cmf}`;
    case "showROC": return `roc_${periods.roc}`;
    case "showMomentum": return `mom_${periods.mom}`;
    case "showTRIX": return `trix_${periods.trix}`;
    case "showChop": return `chop_${periods.chop}`;
    case "showHV": return `historical_volatility_${periods.hv}`;
    case "showVortex": return `vortex_${periods.vortex}`;
    case "showFisher": return `fisher_transform_${periods.fisher}`;
    case "showKST": return "kst";
    case "showCoppock": return "coppock_curve";
    case "showAD": return "ad";
    case "showPVT": return "pvt";
  }
}

function enabledServerNames(indicators: IndicatorState, periods: IndicatorPeriods): string[] {
  return SERVER_INDICATOR_KEYS.filter((key) => indicators[key]).map((key) =>
    serverIndicatorName(key, periods),
  );
}

interface UseServerIndicatorsOptions {
  barsRef: React.MutableRefObject<OhlcvBar[]>;
  indicators: IndicatorState;
  periods: IndicatorPeriods;
}

/**
 * Fetches the enabled server-tier indicator series for the current bars.
 * `refreshServerIndicators` re-posts the CURRENT bars — call it wherever the
 * chart refreshes its client indicators after a data load. Toggle and period
 * changes refetch automatically.
 */
export function useServerIndicators({ barsRef, indicators, periods }: UseServerIndicatorsOptions) {
  const [serverData, setServerData] = useState<ServerIndicatorData>({});
  const requestSeqRef = useRef(0);

  const names = enabledServerNames(indicators, periods);
  const namesSignature = names.join(",");

  const refreshServerIndicators = useCallback(() => {
    const seq = ++requestSeqRef.current;
    const bars = barsRef.current;
    const wanted = namesSignature.length > 0 ? namesSignature.split(",") : [];
    if (wanted.length === 0 || bars.length === 0) {
      setServerData({});
      return;
    }
    const requestBars = bars.slice(-2000).map((b) => ({
      time: b.timestamp,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
      volume: b.volume ?? 0,
    }));
    computeIndicators(requestBars, wanted)
      .then((data) => {
        if (requestSeqRef.current !== seq) return; // stale response
        setServerData(data ?? {});
      })
      .catch(() => {
        // Backend unavailable — keep the last data rather than flickering
        // series away; the toggles simply stop updating until it returns.
      });
    // barsRef is a ref (stable container) — deliberately not a dependency;
    // listing it would refire the effect on every render for consumers that
    // construct the ref object inline.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namesSignature]);

  useEffect(() => {
    refreshServerIndicators();
  }, [refreshServerIndicators]);

  return { serverData, refreshServerIndicators };
}
