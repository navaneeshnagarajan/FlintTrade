/**
 * Sample candlestick pattern scan for demo/disconnected mode.
 * Mirrors the backend make_sample_pattern_scan output.
 */

import type { PatternScan } from "@/types/api";

export const SAMPLE_PATTERN_SCAN: PatternScan = {
  bar_count: 8,
  matches: [
    { index: 2, time: "09:25", pattern: "bullish_engulfing", label: "Bullish Engulfing", direction: "bullish", strength: 0.885 },
    { index: 3, time: "09:30", pattern: "doji", label: "Doji", direction: "neutral", strength: 0.99 },
    { index: 4, time: "09:35", pattern: "hammer", label: "Hammer", direction: "bullish", strength: 0.86 },
    { index: 7, time: "09:50", pattern: "three_white_soldiers", label: "Three White Soldiers", direction: "bullish", strength: 0.93 },
  ],
};
