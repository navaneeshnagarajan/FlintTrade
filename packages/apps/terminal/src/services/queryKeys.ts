/**
 * Centralised TanStack Query key factory for FlintTrade terminal.
 *
 * All query keys live here so invalidation, refetching, and cache access are
 * consistent across hooks and components.  Use the leaf helpers (e.g.
 * `queryKeys.positions.list(scope)`) instead of bare string arrays everywhere.
 *
 * Convention:
 *   `.all`   — root key (invalidates the entire namespace)
 *   `.list(scope)` — the concrete query key used in useQuery
 *   `.detail(id)` — per-item variant where applicable
 */

export const queryKeys = {
  // -------------------------------------------------------------------------
  // Account / trading
  // -------------------------------------------------------------------------
  positions: {
    all: ["positions"] as const,
    list: (scope: string) => [...queryKeys.positions.all, "list", scope] as const,
  },
  orders: {
    all: ["orders"] as const,
    list: (scope: string) => [...queryKeys.orders.all, "list", scope] as const,
  },
  tradebook: {
    all: ["tradebook"] as const,
    list: (scope: string) => [...queryKeys.tradebook.all, "list", scope] as const,
  },
  holdings: {
    all: ["holdings"] as const,
    list: (scope: string) => [...queryKeys.holdings.all, "list", scope] as const,
  },
  funds: {
    all: ["funds"] as const,
    detail: (scope: string) => [...queryKeys.funds.all, "detail", scope] as const,
  },
  margin: {
    all: ["margin"] as const,
    detail: (
      scope: string,
      symbol: string,
      exchange: string,
      qty: number,
      product: string,
      action: string,
    ) =>
      [
        ...queryKeys.margin.all,
        scope,
        symbol,
        exchange,
        qty,
        product,
        action,
      ] as const,
  },

  // -------------------------------------------------------------------------
  // Market data
  // -------------------------------------------------------------------------
  optionChain: {
    all: ["optionchain"] as const,
    detail: (symbol: string, exchange: string, expiry: string) =>
      [...queryKeys.optionChain.all, symbol, exchange, expiry] as const,
  },
  syntheticFuture: {
    all: ["syntheticFuture"] as const,
    detail: (symbol: string, exchange: string, expiry: string) =>
      [...queryKeys.syntheticFuture.all, symbol, exchange, expiry] as const,
  },

  // -------------------------------------------------------------------------
  // Market status / meta
  // -------------------------------------------------------------------------
  holidays: {
    all: ["holidays"] as const,
    list: () => [...queryKeys.holidays.all, "list"] as const,
  },
  timings: {
    all: ["timings"] as const,
    detail: () => [...queryKeys.timings.all, "detail"] as const,
  },

  // -------------------------------------------------------------------------
  // Broker / connection
  // -------------------------------------------------------------------------
  brokerList: {
    all: ["brokerList"] as const,
    list: () => [...queryKeys.brokerList.all, "list"] as const,
  },
  brokerAccounts: {
    all: ["brokerAccounts"] as const,
    list: () => [...queryKeys.brokerAccounts.all, "list"] as const,
  },
  brokerCapabilities: {
    all: ["brokerCapabilities"] as const,
    detail: (broker: string) =>
      [...queryKeys.brokerCapabilities.all, broker] as const,
  },

  // -------------------------------------------------------------------------
  // Analysis / AI
  // -------------------------------------------------------------------------
  signals: {
    all: ["signals"] as const,
    list: () => [...queryKeys.signals.all, "list"] as const,
  },

  // -------------------------------------------------------------------------
  // Trade journal (annotated SQLite + FTS5 store)
  // -------------------------------------------------------------------------
  journal: {
    all: ["journal"] as const,
    list: (search: string, side: string, strategy: string) =>
      [...queryKeys.journal.all, "list", search, side, strategy] as const,
    stats: () => [...queryKeys.journal.all, "stats"] as const,
  },
} as const;
