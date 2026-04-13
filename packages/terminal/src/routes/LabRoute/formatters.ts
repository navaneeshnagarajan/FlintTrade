export function fmtInr(value: number): string {
  return value.toLocaleString("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  });
}

export function fmtPct(value: number): string {
  return (value * 100).toFixed(2) + "%";
}

export function fmtNum(value: number, decimals = 2): string {
  return value.toFixed(decimals);
}
