/**
 * Invest-route formatter re-exports.
 *
 * Canonical implementations live in `@/lib/formatters`. This module keeps
 * existing `./formatters` imports working without duplicating logic.
 */

export { formatINR, formatPercent } from "@/lib/formatters";
export { formatCurrencyCompact as formatINRCompact } from "@/lib/formatters";
