/**
 * Strategy Lab query hydration.
 *
 * AI Deploy (and any other deep link) opens `/lab?strategy=<registryKey>`.
 * These helpers resolve that query against the loaded catalogue so the
 * Backtest selector populates and Run Backtest can enable — including the
 * public demo, whose sample catalogue may omit the linked key.
 */

import type { StrategyInfo } from "@/services/ftApi";

/** Registry keys are identifiers (PascalCase or snake_case), not free text. */
const STRATEGY_QUERY_RE = /^[A-Za-z][A-Za-z0-9_]{0,127}$/;

/**
 * Normalise a `?strategy=` value. Empty, blank, or unsafe strings are ignored
 * so a crafted URL cannot inject a selector option.
 */
export function readStrategyQuery(raw: string | null | undefined): string | null {
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  if (!STRATEGY_QUERY_RE.test(trimmed)) return null;
  return trimmed;
}

function matchCatalogueStrategy<T extends { name: string }>(
  query: string,
  catalogue: readonly T[],
): T | undefined {
  const exact = catalogue.find((strategy) => strategy.name === query);
  if (exact) return exact;
  const lower = query.toLowerCase();
  return catalogue.find((strategy) => strategy.name.toLowerCase() === lower);
}

/**
 * Catalogue name when the query matches a loaded strategy; otherwise the
 * query key itself so a pending or demo-missing name can still be selected.
 */
export function resolveSelectedStrategy(
  query: string | null | undefined,
  catalogue: readonly StrategyInfo[],
): string {
  const key = readStrategyQuery(query);
  if (!key) return "";
  return matchCatalogueStrategy(key, catalogue)?.name ?? key;
}

/**
 * Keep a linked registry key visible in the selector when the loaded list
 * does not include it (demo sample catalogue, or a catalogue that has not
 * arrived yet).
 */
export function mergeQueryStrategy(
  catalogue: readonly StrategyInfo[],
  query: string | null | undefined,
): StrategyInfo[] {
  const key = readStrategyQuery(query);
  if (!key) return [...catalogue];
  if (matchCatalogueStrategy(key, catalogue)) return [...catalogue];
  return [
    ...catalogue,
    {
      name: key,
      description: "Opened from a strategy link",
      category: "Linked",
      parameters: [],
    },
  ];
}
