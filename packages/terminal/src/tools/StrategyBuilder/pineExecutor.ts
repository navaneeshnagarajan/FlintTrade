/**
 * pineExecutor.ts
 *
 * Simplified Pine Script executor for FlintTrade Strategy Builder.
 *
 * Supports a practical subset of Pine Script v5 patterns:
 *   - strategy() declaration (parsed for metadata)
 *   - ta.sma(), ta.ema(), ta.rsi(), ta.macd(), ta.atr(), ta.bbands()
 *   - crossover(), crossunder() (both top-level and ta.crossover / ta.crossunder)
 *   - strategy.entry("Label", strategy.long / strategy.short)
 *   - strategy.close("Label")
 *   - plot() calls (color extraction: color.blue, color.red, color.green, color.orange, color.purple, color.yellow)
 *   - Built-in series: close, open, high, low, volume
 *
 * Approach: regex-based extraction rather than a full AST parser.
 * Each supported call pattern is matched, evaluated against the full bar
 * series, and the resulting values are stored in a named variable map.
 * Subsequent references to those variable names resolve correctly.
 *
 * Limitations (by design — these are not bugs):
 *   - Arithmetic expressions between variables (e.g. fast - slow) produce a
 *     special DiffSeries placeholder resolved at crossover/entry evaluation.
 *   - if/else blocks are single-line only (nested blocks not supported).
 *   - strategy.entry conditions inside multiline if blocks are parsed as
 *     standalone entries on the first matching crossover/condition line.
 *
 * No external dependencies. All indicator functions come from @/lib/indicators.
 */

import { sma, ema, rsi, macd, atr, bollingerBands } from "@/lib/indicators";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface BarData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PinePlot {
  name: string;
  values: number[];
  /** Resolved CSS color string for rendering */
  color: string;
  /** Offset from bar 0 where values begin (due to lookback) */
  offset: number;
}

export interface PineSignal {
  /** Zero-based bar index */
  bar: number;
  type: "BUY" | "SELL";
  label: string;
}

export interface PineResult {
  plots: PinePlot[];
  signals: PineSignal[];
  errors: string[];
  strategyName: string;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Map Pine Script color names to Tailwind-friendly hex values */
const COLOR_MAP: Record<string, string> = {
  "color.blue": "#3b82f6",
  "color.red": "#ef4444",
  "color.green": "#22c55e",
  "color.orange": "#f97316",
  "color.purple": "#a855f7",
  "color.yellow": "#eab308",
  "color.white": "#ffffff",
  "color.gray": "#6b7280",
  "color.teal": "#14b8a6",
  "color.lime": "#84cc16",
  "color.fuchsia": "#e879f9",
  "color.new": "#3b82f6", // fallback for color.new(...)
};

function resolveColor(raw: string | undefined): string {
  if (!raw) return "#3b82f6";
  const trimmed = raw.trim();
  // color.new(hex, opacity) — extract the hex portion
  const colorNewMatch = trimmed.match(/color\.new\s*\(\s*color\.(\w+)/);
  if (colorNewMatch) {
    return COLOR_MAP[`color.${colorNewMatch[1]}`] ?? "#3b82f6";
  }
  return COLOR_MAP[trimmed] ?? trimmed;
}

/** Strip Pine Script comments (// to end of line) */
function stripComments(code: string): string {
  return code
    .split("\n")
    .map((line) => line.replace(/\/\/.*$/, ""))
    .join("\n");
}

/** Extract a numeric argument from a call like "ta.sma(close, 20)" → 20 */
function parseIntArg(raw: string): number {
  const n = parseInt(raw.trim(), 10);
  return Number.isNaN(n) ? 0 : n;
}

/**
 * Pad a shorter indicator result to align with the full bar series.
 * Indicators have a lookback — their output starts at bar index `offset`.
 * This returns { values, offset } so the renderer can skip the leading bars.
 */
function alignedSeries(raw: number[], barCount: number): { values: number[]; offset: number } {
  const offset = barCount - raw.length;
  return { values: raw, offset };
}

// ---------------------------------------------------------------------------
// Variable resolution context
// ---------------------------------------------------------------------------

type SeriesRef = { values: number[]; offset: number };
type VarMap = Map<string, SeriesRef>;

/** Build a SeriesRef from a full-length array (no offset). */
function fullSeries(values: number[]): SeriesRef {
  return { values, offset: 0 };
}

/**
 * Resolve a name that is either a built-in series name or a previously
 * declared variable. Returns null if not found.
 */
function resolveVar(name: string, builtins: VarMap, vars: VarMap): SeriesRef | null {
  return vars.get(name) ?? builtins.get(name) ?? null;
}

/** Compute element-wise difference between two aligned series. */
function diffSeries(a: SeriesRef, b: SeriesRef): SeriesRef {
  // Align by taking the shorter overlap from the end
  const lenA = a.values.length;
  const lenB = b.values.length;
  const len = Math.min(lenA, lenB);
  const offset = Math.max(a.offset, b.offset);
  const valA = a.values.slice(lenA - len);
  const valB = b.values.slice(lenB - len);
  return {
    values: valA.map((v, i) => v - valB[i]),
    offset,
  };
}

/** Crossover: series A crosses above series B at bar i */
function crossoverSeries(a: SeriesRef, b: SeriesRef): boolean[] {
  // Work with aligned tails
  const lenA = a.values.length;
  const lenB = b.values.length;
  const len = Math.min(lenA, lenB);
  const vA = a.values.slice(lenA - len);
  const vB = b.values.slice(lenB - len);
  const result: boolean[] = [false];
  for (let i = 1; i < len; i++) {
    result.push(vA[i - 1] < vB[i - 1] && vA[i] > vB[i]);
  }
  return result;
}

/** Crossunder: series A crosses below series B at bar i */
function crossunderSeries(a: SeriesRef, b: SeriesRef): boolean[] {
  const lenA = a.values.length;
  const lenB = b.values.length;
  const len = Math.min(lenA, lenB);
  const vA = a.values.slice(lenA - len);
  const vB = b.values.slice(lenB - len);
  const result: boolean[] = [false];
  for (let i = 1; i < len; i++) {
    result.push(vA[i - 1] > vB[i - 1] && vA[i] < vB[i]);
  }
  return result;
}

/**
 * Given a boolean[] from crossover/crossunder (aligned to some offset)
 * and the total barCount, return the absolute bar indices where true.
 */
function boolToBarIndices(flags: boolean[], offset: number): number[] {
  return flags.reduce<number[]>((acc, f, i) => {
    if (f) acc.push(offset + i);
    return acc;
  }, []);
}

// ---------------------------------------------------------------------------
// Pattern matching helpers (regex-based)
// ---------------------------------------------------------------------------

// Matches:  varName = ta.sma(source, period)
const RE_SMA = /^(\w+)\s*=\s*ta\.sma\s*\(\s*(\w+)\s*,\s*(\d+)\s*\)/;
const RE_EMA = /^(\w+)\s*=\s*ta\.ema\s*\(\s*(\w+)\s*,\s*(\d+)\s*\)/;
const RE_RSI = /^(\w+)\s*=\s*ta\.rsi\s*\(\s*(\w+)\s*,\s*(\d+)\s*\)/;
const RE_ATR = /^(\w+)\s*=\s*ta\.atr\s*\(\s*(\d+)\s*\)/;
const RE_MACD = /^(\w+)\s*=\s*ta\.macd\s*\(\s*(\w+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)/;
const RE_BBANDS = /^(\w+)\s*=\s*ta\.bb\s*\(\s*(\w+)\s*,\s*(\d+)\s*,\s*(\d+(?:\.\d+)?)\s*\)/;

// Matches:  varName = fast - slow  (diff of two known vars)
const RE_DIFF = /^(\w+)\s*=\s*(\w+)\s*-\s*(\w+)/;

// Matches:  if ta.crossover(a, b)  or  if crossover(a, b)
const RE_IF_CROSSOVER = /^\s*if\s+(?:ta\.)?crossover\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)/;
const RE_IF_CROSSUNDER = /^\s*if\s+(?:ta\.)?crossunder\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)/;
// RSI threshold conditions
const RE_IF_RSI_ABOVE = /^\s*if\s+(\w+)\s*(?:>|>=)\s*(\d+(?:\.\d+)?)/;
const RE_IF_RSI_BELOW = /^\s*if\s+(\w+)\s*(?:<|<=)\s*(\d+(?:\.\d+)?)/;

// Matches:  strategy.entry("Label", strategy.long)  or  strategy.entry("Label", strategy.short)
const RE_ENTRY_LONG = /strategy\.entry\s*\(\s*["']([^"']+)["']\s*,\s*strategy\.long\s*\)/;
const RE_ENTRY_SHORT = /strategy\.entry\s*\(\s*["']([^"']+)["']\s*,\s*strategy\.short\s*\)/;
// Matches:  strategy.close("Label")
const RE_CLOSE = /strategy\.close\s*\(\s*["']([^"']+)["']\s*\)/;

// Matches:  plot(varName, title="...", color=color.blue)
const RE_PLOT = /^plot\s*\(\s*(\w+)\s*(?:,\s*title\s*=\s*["']([^"']+)["'])?\s*(?:,\s*color\s*=\s*([^,)]+))?\s*\)/;
// Matches:  plot(varName, "title", color.blue)  (positional args variant)
const RE_PLOT_POS = /^plot\s*\(\s*(\w+)\s*,\s*["']([^"']+)["']\s*,\s*(color\.\w+[^,)]*)\s*\)/;

// Matches:  strategy("Name", ...)
const RE_STRATEGY = /strategy\s*\(\s*["']([^"']+)["']/;

// ---------------------------------------------------------------------------
// Main executor
// ---------------------------------------------------------------------------

export function executePineScript(code: string, bars: BarData[]): PineResult {
  const plots: PinePlot[] = [];
  const signals: PineSignal[] = [];
  const errors: string[] = [];
  let strategyName = "Pine Strategy";

  if (bars.length < 2) {
    return { plots, signals, errors: ["Not enough bar data (minimum 2 bars required)"], strategyName };
  }

  const barCount = bars.length;

  // Extract OHLCV arrays
  const closes = bars.map((b) => b.close);
  const opens = bars.map((b) => b.open);
  const highs = bars.map((b) => b.high);
  const lows = bars.map((b) => b.low);
  const volumes = bars.map((b) => b.volume);

  // Built-in series
  const builtins: VarMap = new Map([
    ["close", fullSeries(closes)],
    ["open", fullSeries(opens)],
    ["high", fullSeries(highs)],
    ["low", fullSeries(lows)],
    ["volume", fullSeries(volumes)],
  ]);

  // User-declared variables
  const vars: VarMap = new Map();

  // Strip comments, normalize whitespace
  const cleaned = stripComments(code);
  const lines = cleaned.split("\n").map((l) => l.trim()).filter(Boolean);

  // ---- Pass 1: strategy name ----
  for (const line of lines) {
    const m = line.match(RE_STRATEGY);
    if (m) {
      strategyName = m[1];
      break;
    }
  }

  // ---- Pass 2: variable declarations and indicator calculations ----
  // We make two sub-passes: first compute all indicators, then handle diffs.
  // This ensures that vars referred to in diff expressions are already resolved.

  for (const line of lines) {
    // ta.sma
    const smM = line.match(RE_SMA);
    if (smM) {
      const [, varName, source, periodStr] = smM;
      const src = resolveVar(source, builtins, vars);
      if (src) {
        const period = parseIntArg(periodStr);
        const raw = sma(src.values, period);
        if (raw.length === 0) {
          errors.push(`ta.sma(${source}, ${periodStr}): not enough data (${src.values.length} bars, need ${period})`);
        } else {
          vars.set(varName, alignedSeries(raw, barCount));
        }
      } else {
        errors.push(`ta.sma: unknown source series '${source}'`);
      }
      continue;
    }

    // ta.ema
    const emM = line.match(RE_EMA);
    if (emM) {
      const [, varName, source, periodStr] = emM;
      const src = resolveVar(source, builtins, vars);
      if (src) {
        const period = parseIntArg(periodStr);
        const raw = ema(src.values, period);
        if (raw.length === 0) {
          errors.push(`ta.ema(${source}, ${periodStr}): not enough data (${src.values.length} bars, need ${period})`);
        } else {
          vars.set(varName, alignedSeries(raw, barCount));
        }
      } else {
        errors.push(`ta.ema: unknown source series '${source}'`);
      }
      continue;
    }

    // ta.rsi
    const rsM = line.match(RE_RSI);
    if (rsM) {
      const [, varName, source, periodStr] = rsM;
      const src = resolveVar(source, builtins, vars);
      if (src) {
        const period = parseIntArg(periodStr);
        const raw = rsi(src.values, period);
        if (raw.length === 0) {
          errors.push(`ta.rsi(${source}, ${periodStr}): not enough data (${src.values.length} bars, need ${period + 1})`);
        } else {
          vars.set(varName, alignedSeries(raw, barCount));
        }
      } else {
        errors.push(`ta.rsi: unknown source series '${source}'`);
      }
      continue;
    }

    // ta.atr
    const atM = line.match(RE_ATR);
    if (atM) {
      const [, varName, periodStr] = atM;
      const period = parseIntArg(periodStr);
      const raw = atr(highs, lows, closes, period);
      if (raw.length === 0) {
        errors.push(`ta.atr(${periodStr}): not enough data (${barCount} bars, need ${period + 1})`);
      } else {
        vars.set(varName, alignedSeries(raw, barCount));
      }
      continue;
    }

    // ta.macd — stores three sub-series: varName (macd line), varName_signal, varName_hist
    const mcM = line.match(RE_MACD);
    if (mcM) {
      const [, varName, source, fastStr, slowStr, signalStr] = mcM;
      const src = resolveVar(source, builtins, vars);
      if (src) {
        const fast = parseIntArg(fastStr);
        const slow = parseIntArg(slowStr);
        const signal = parseIntArg(signalStr);
        const result = macd(src.values, fast, slow, signal);
        if (result.macd.length === 0) {
          errors.push(`ta.macd: not enough data (${src.values.length} bars, need ${slow + signal - 1})`);
        } else {
          vars.set(varName, alignedSeries(result.macd, barCount));
          vars.set(`${varName}_signal`, alignedSeries(result.signal, barCount));
          vars.set(`${varName}_hist`, alignedSeries(result.histogram, barCount));
        }
      } else {
        errors.push(`ta.macd: unknown source series '${source}'`);
      }
      continue;
    }

    // ta.bb
    const bbM = line.match(RE_BBANDS);
    if (bbM) {
      const [, varName, source, periodStr, multStr] = bbM;
      const src = resolveVar(source, builtins, vars);
      if (src) {
        const period = parseIntArg(periodStr);
        const mult = parseFloat(multStr);
        const bands = bollingerBands(src.values, period, mult);
        if (bands.length === 0) {
          errors.push(`ta.bb: not enough data (${src.values.length} bars, need ${period})`);
        } else {
          vars.set(`${varName}_upper`, alignedSeries(bands.map((b) => b.upper), barCount));
          vars.set(`${varName}_middle`, alignedSeries(bands.map((b) => b.middle), barCount));
          vars.set(`${varName}_lower`, alignedSeries(bands.map((b) => b.lower), barCount));
          // Set varName itself to middle for generic references
          vars.set(varName, alignedSeries(bands.map((b) => b.middle), barCount));
        }
      } else {
        errors.push(`ta.bb: unknown source series '${source}'`);
      }
      continue;
    }
  }

  // Second sub-pass: variable differences (e.g. hist = macd - signal)
  for (const line of lines) {
    const dfM = line.match(RE_DIFF);
    if (dfM) {
      const [, varName, aName, bName] = dfM;
      // Only process if not already set and both operands are known
      if (!vars.has(varName) && !builtins.has(varName)) {
        const aRef = resolveVar(aName, builtins, vars);
        const bRef = resolveVar(bName, builtins, vars);
        if (aRef && bRef) {
          vars.set(varName, diffSeries(aRef, bRef));
        }
      }
    }
  }

  // ---- Pass 3: plot() declarations ----
  for (const line of lines) {
    let plotMatch = line.match(RE_PLOT);
    if (!plotMatch) {
      plotMatch = line.match(RE_PLOT_POS);
    }
    if (plotMatch) {
      const varName = plotMatch[1];
      const title = plotMatch[2] ?? varName;
      const colorRaw = plotMatch[3];
      const colorHex = resolveColor(colorRaw);
      const ref = resolveVar(varName, builtins, vars);
      if (ref) {
        plots.push({
          name: title,
          values: ref.values,
          color: colorHex,
          offset: ref.offset,
        });
      } else {
        // Suppress "plot of built-in volume" noise — volume is rarely charted on price
        if (varName !== "volume") {
          errors.push(`plot: unknown variable '${varName}'`);
        }
      }
    }
  }

  // ---- Pass 4: strategy.entry / strategy.close inside if blocks ----
  // We process lines in pairs: the `if condition` line followed by the body line.
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // if ta.crossover(a, b)  or  if crossover(a, b)
    const coMatch = line.match(RE_IF_CROSSOVER);
    if (coMatch) {
      const [, aName, bName] = coMatch;
      const aRef = resolveVar(aName, builtins, vars);
      const bRef = resolveVar(bName, builtins, vars);
      if (aRef && bRef) {
        const flags = crossoverSeries(aRef, bRef);
        const coOffset = Math.max(aRef.offset, bRef.offset);
        const crossBars = boolToBarIndices(flags, coOffset);

        // Look ahead for strategy.entry / strategy.close on next non-empty line
        const bodyLine = lines[i + 1] ?? "";
        const entLong = bodyLine.match(RE_ENTRY_LONG);
        const entShort = bodyLine.match(RE_ENTRY_SHORT);
        const closeLong = bodyLine.match(RE_CLOSE);

        if (entLong) {
          const label = entLong[1];
          for (const bar of crossBars) {
            if (bar < barCount) signals.push({ bar, type: "BUY", label });
          }
        } else if (entShort) {
          const label = entShort[1];
          for (const bar of crossBars) {
            if (bar < barCount) signals.push({ bar, type: "SELL", label });
          }
        } else if (closeLong) {
          const label = closeLong[1];
          for (const bar of crossBars) {
            if (bar < barCount) signals.push({ bar, type: "SELL", label });
          }
        }
        // Also check if the strategy call is on the same line (one-liner)
        const sameLong = line.match(RE_ENTRY_LONG);
        const sameShort = line.match(RE_ENTRY_SHORT);
        if (sameLong) {
          for (const bar of crossBars) {
            if (bar < barCount) signals.push({ bar, type: "BUY", label: sameLong[1] });
          }
        } else if (sameShort) {
          for (const bar of crossBars) {
            if (bar < barCount) signals.push({ bar, type: "SELL", label: sameShort[1] });
          }
        }
      } else {
        if (!aRef) errors.push(`crossover: unknown variable '${aName}'`);
        if (!bRef) errors.push(`crossover: unknown variable '${bName}'`);
      }
      continue;
    }

    // if ta.crossunder(a, b)
    const cuMatch = line.match(RE_IF_CROSSUNDER);
    if (cuMatch) {
      const [, aName, bName] = cuMatch;
      const aRef = resolveVar(aName, builtins, vars);
      const bRef = resolveVar(bName, builtins, vars);
      if (aRef && bRef) {
        const flags = crossunderSeries(aRef, bRef);
        const cuOffset = Math.max(aRef.offset, bRef.offset);
        const crossBars = boolToBarIndices(flags, cuOffset);

        const bodyLine = lines[i + 1] ?? "";
        const entLong = bodyLine.match(RE_ENTRY_LONG);
        const entShort = bodyLine.match(RE_ENTRY_SHORT);
        const closeLong = bodyLine.match(RE_CLOSE);

        if (entLong) {
          const label = entLong[1];
          for (const bar of crossBars) {
            if (bar < barCount) signals.push({ bar, type: "BUY", label });
          }
        } else if (entShort) {
          const label = entShort[1];
          for (const bar of crossBars) {
            if (bar < barCount) signals.push({ bar, type: "SELL", label });
          }
        } else if (closeLong) {
          const label = closeLong[1];
          for (const bar of crossBars) {
            if (bar < barCount) signals.push({ bar, type: "SELL", label });
          }
        }
        // Same-line check
        const sameLong = line.match(RE_ENTRY_LONG);
        const sameShort = line.match(RE_ENTRY_SHORT);
        if (sameLong) {
          for (const bar of crossBars) {
            if (bar < barCount) signals.push({ bar, type: "BUY", label: sameLong[1] });
          }
        } else if (sameShort) {
          for (const bar of crossBars) {
            if (bar < barCount) signals.push({ bar, type: "SELL", label: sameShort[1] });
          }
        }
      } else {
        if (!aRef) errors.push(`crossunder: unknown variable '${aName}'`);
        if (!bRef) errors.push(`crossunder: unknown variable '${bName}'`);
      }
      continue;
    }

    // if rsiVar > threshold  (e.g. RSI overbought)
    const rsiAboveMatch = line.match(RE_IF_RSI_ABOVE);
    if (rsiAboveMatch) {
      const [, varName, thresholdStr] = rsiAboveMatch;
      const ref = resolveVar(varName, builtins, vars);
      if (ref) {
        const threshold = parseFloat(thresholdStr);
        const bodyLine = lines[i + 1] ?? "";
        const entShort = bodyLine.match(RE_ENTRY_SHORT);
        const closeLong = bodyLine.match(RE_CLOSE);
        for (let j = 1; j < ref.values.length; j++) {
          const bar = ref.offset + j;
          if (bar >= barCount) break;
          const prev = ref.values[j - 1];
          const curr = ref.values[j];
          // "enters overbought zone" — transition from below to above
          if (prev < threshold && curr >= threshold) {
            if (entShort) {
              signals.push({ bar, type: "SELL", label: entShort[1] });
            } else if (closeLong) {
              signals.push({ bar, type: "SELL", label: closeLong[1] });
            }
          }
        }
      }
      continue;
    }

    // if rsiVar < threshold  (e.g. RSI oversold)
    const rsiBelowMatch = line.match(RE_IF_RSI_BELOW);
    if (rsiBelowMatch) {
      const [, varName, thresholdStr] = rsiBelowMatch;
      const ref = resolveVar(varName, builtins, vars);
      if (ref) {
        const threshold = parseFloat(thresholdStr);
        const bodyLine = lines[i + 1] ?? "";
        const entLong = bodyLine.match(RE_ENTRY_LONG);
        for (let j = 1; j < ref.values.length; j++) {
          const bar = ref.offset + j;
          if (bar >= barCount) break;
          const prev = ref.values[j - 1];
          const curr = ref.values[j];
          // "enters oversold zone" — transition from above to below
          if (prev > threshold && curr <= threshold) {
            if (entLong) {
              signals.push({ bar, type: "BUY", label: entLong[1] });
            }
          }
        }
      }
      continue;
    }
  }

  // Deduplicate signals at the same bar (same bar + same type = keep first occurrence)
  const seenSignals = new Set<string>();
  const dedupedSignals = signals.filter((s) => {
    const key = `${s.bar}-${s.type}`;
    if (seenSignals.has(key)) return false;
    seenSignals.add(key);
    return true;
  });

  return { plots, signals: dedupedSignals, errors, strategyName };
}
