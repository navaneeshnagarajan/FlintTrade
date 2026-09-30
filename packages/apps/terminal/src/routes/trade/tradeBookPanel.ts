/** Default height of the Trade desk book, as a percentage of the workspace. */
export const TRADE_BOOK_PANEL_DEFAULT_PERCENT = 28;

export type TradeBookTab = "positions" | "orders";

/** `/trade#positions` and `/trade#orders` open that book tab. */
export function tradeBookTabFromHash(hash: string | undefined): TradeBookTab | null {
  const id = (hash ?? "").replace(/^#/, "");
  if (id === "positions" || id === "orders") return id;
  return null;
}
