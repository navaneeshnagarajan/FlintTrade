/**
 * Check if Indian equity markets are currently open.
 * NSE/BSE/NFO/BFO: 9:15 AM - 3:30 PM IST (Mon-Fri)
 */
export function isMarketHours(): boolean {
  const ist = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }),
  );
  const mins = ist.getHours() * 60 + ist.getMinutes();
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  return mins >= 555 && mins <= 930;
}
