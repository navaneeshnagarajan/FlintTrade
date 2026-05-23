/**
 * MCX (Multi Commodity Exchange) lot sizes and commodity metadata.
 *
 * Lot sizes represent the contract unit for each commodity on MCX.
 * These are used for margin calculations, order quantity validation,
 * and display in trading widgets.
 */

// ---------------------------------------------------------------------------
// Lot sizes (contract units)
// ---------------------------------------------------------------------------

export const MCX_LOT_SIZES: Record<string, number> = {
  // Bullion
  GOLD: 100,           // 100 grams
  GOLDM: 10,           // 10 grams (Gold Mini)
  GOLDPETAL: 1,        // 1 gram (Gold Petal)
  SILVER: 30000,       // 30 kg (in grams)
  SILVERM: 5000,       // 5 kg (Silver Mini, in grams)
  SILVERMIC: 1000,     // 1 kg (Silver Micro, in grams)

  // Energy
  CRUDEOIL: 100,       // 100 barrels
  CRUDEOILM: 10,       // 10 barrels (Crude Mini)
  NATURALGAS: 1250,    // 1250 MMBtu

  // Base metals
  COPPER: 2500,        // 2.5 tonnes (in kg)
  COPPERM: 250,        // 250 kg (Copper Mini)
  ZINC: 5000,          // 5 tonnes (in kg)
  ZINCMINI: 1000,      // 1 tonne (in kg)
  LEAD: 5000,          // 5 tonnes (in kg)
  LEADMINI: 1000,      // 1 tonne (in kg)
  NICKEL: 1500,        // 1.5 tonnes (in kg)
  NICKELMINI: 100,     // 100 kg (Nickel Mini)
  ALUMINIUM: 5000,     // 5 tonnes (in kg)
  ALUMINI: 1000,       // 1 tonne (in kg)

  // Agri
  MENTHAOIL: 360,      // 360 kg
  COTTON: 25,          // 25 bales
};

// ---------------------------------------------------------------------------
// Price tick sizes
// ---------------------------------------------------------------------------

/** Minimum price movement (tick size) per commodity. */
export const MCX_TICK_SIZES: Record<string, number> = {
  GOLD: 1,
  GOLDM: 1,
  GOLDPETAL: 1,
  SILVER: 1,
  SILVERM: 1,
  SILVERMIC: 1,
  CRUDEOIL: 1,
  CRUDEOILM: 1,
  NATURALGAS: 0.1,
  COPPER: 0.05,
  COPPERM: 0.05,
  ZINC: 0.05,
  ZINCMINI: 0.05,
  LEAD: 0.05,
  LEADMINI: 0.05,
  NICKEL: 0.1,
  NICKELMINI: 0.1,
  ALUMINIUM: 0.05,
  ALUMINI: 0.05,
  MENTHAOIL: 0.1,
  COTTON: 10,
};

// ---------------------------------------------------------------------------
// Unit descriptions (for display)
// ---------------------------------------------------------------------------

/** Human-readable unit for each commodity (used in tooltips and labels). */
export const MCX_UNITS: Record<string, string> = {
  GOLD: "grams",
  GOLDM: "grams",
  GOLDPETAL: "gram",
  SILVER: "grams",
  SILVERM: "grams",
  SILVERMIC: "grams",
  CRUDEOIL: "barrels",
  CRUDEOILM: "barrels",
  NATURALGAS: "MMBtu",
  COPPER: "kg",
  COPPERM: "kg",
  ZINC: "kg",
  ZINCMINI: "kg",
  LEAD: "kg",
  LEADMINI: "kg",
  NICKEL: "kg",
  NICKELMINI: "kg",
  ALUMINIUM: "kg",
  ALUMINI: "kg",
  MENTHAOIL: "kg",
  COTTON: "bales",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Known MCX commodity symbols. */
export const MCX_COMMODITIES = Object.keys(MCX_LOT_SIZES);

/**
 * Get the lot size for an MCX commodity.
 * Returns 1 if the symbol is unknown.
 */
export function getMCXLotSize(symbol: string): number {
  return MCX_LOT_SIZES[symbol.toUpperCase()] ?? 1;
}

/**
 * Get the tick size for an MCX commodity.
 * Returns 1 if the symbol is unknown.
 */
export function getMCXTickSize(symbol: string): number {
  return MCX_TICK_SIZES[symbol.toUpperCase()] ?? 1;
}

/**
 * Get the display unit for an MCX commodity.
 * Returns "units" if the symbol is unknown.
 */
export function getMCXUnit(symbol: string): string {
  return MCX_UNITS[symbol.toUpperCase()] ?? "units";
}

/**
 * Check if a symbol is a known MCX commodity.
 */
export function isMCXCommodity(symbol: string): boolean {
  return symbol.toUpperCase() in MCX_LOT_SIZES;
}
