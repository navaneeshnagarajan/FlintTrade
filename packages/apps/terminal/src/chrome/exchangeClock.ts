/** Indian exchange zone. The footer clock uses this, not the machine zone. */
export const EXCHANGE_TIME_ZONE = "Asia/Kolkata";

/**
 * Clock label for the footer, for example `14:18:05 IST`.
 *
 * Hours stay on a 24-hour clock in Asia/Kolkata.
 */
export function formatExchangeClock(date: Date): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: EXCHANGE_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const pick = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "00";
  return `${pick("hour")}:${pick("minute")}:${pick("second")} IST`;
}
