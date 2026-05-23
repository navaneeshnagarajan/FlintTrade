// ─── Scalper — pure helper functions ──────────────────────────────────────────

export const fmt2 = (n: number | null | undefined): string =>
  n == null || isNaN(n) ? "—" : Number(n).toFixed(2);

export const fmtInt = (n: number | null | undefined): string =>
  n == null || isNaN(n) ? "—" : Math.round(n).toLocaleString("en-IN");

export function roundToStrike(price: number, step: number): number {
  return Math.round(price / step) * step;
}

export function buildOptionSymbol(
  base: string,
  expiry: string,
  strike: number,
  type: "CE" | "PE",
): string | null {
  if (!expiry) return null;
  let exp = expiry;
  if (exp.includes("-")) {
    const d = new Date(exp);
    const day = String(d.getDate()).padStart(2, "0");
    const mon = d.toLocaleString("en-US", { month: "short" }).toUpperCase();
    const yr = String(d.getFullYear()).slice(2);
    exp = `${day}${mon}${yr}`;
  }
  return `${base}${exp}${strike}${type}`;
}
