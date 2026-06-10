/** Render an em dash for absent/non-finite values so a single missing metric
 * never crashes the surrounding card (e.g. an undefined backend field). */
function isNum(value: number): boolean {
  return typeof value === "number" && Number.isFinite(value);
}

export function fmtInr(value: number): string {
  if (!isNum(value)) return "—";
  return value.toLocaleString("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  });
}

export function fmtPct(value: number): string {
  if (!isNum(value)) return "—";
  return (value * 100).toFixed(2) + "%";
}

export function fmtNum(value: number, decimals = 2): string {
  if (!isNum(value)) return "—";
  return value.toFixed(decimals);
}
