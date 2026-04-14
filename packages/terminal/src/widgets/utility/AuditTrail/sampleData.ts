/**
 * Sample audit trail entries for explore/disconnected mode.
 * All data is illustrative — no real user/IP data.
 */

import type { ActivityEntry } from "@/services/ftApi";

function isoOffset(seconds: number): string {
  return new Date(Date.now() - seconds * 1000).toISOString();
}

export const SAMPLE_AUDIT_ENTRIES: ActivityEntry[] = [
  { id: 1,  timestamp: isoOffset(30),    action: "order_placed",    user: "trader",  details: "BUY NIFTY 22500 CE 1 lot @ MKT",        ip: "192.0.2.10" },
  { id: 2,  timestamp: isoOffset(90),    action: "order_cancelled", user: "trader",  details: "CANCEL order #ORD-2042",                 ip: "192.0.2.10" },
  { id: 3,  timestamp: isoOffset(180),   action: "position_closed", user: "trader",  details: "CLOSE BANKNIFTY 47000 PE short position", ip: "192.0.2.10" },
  { id: 4,  timestamp: isoOffset(600),   action: "settings_changed", user: "trader", details: "Theme changed: Graphite → Midnight",      ip: "192.0.2.10" },
  { id: 5,  timestamp: isoOffset(1200),  action: "login",           user: "trader",  details: "Login successful",                       ip: "192.0.2.10" },
  { id: 6,  timestamp: isoOffset(3600),  action: "order_placed",    user: "trader",  details: "SELL RELIANCE FUT 1 lot @ LMT 2950",     ip: "192.0.2.10" },
  { id: 7,  timestamp: isoOffset(7200),  action: "order_modified",  user: "trader",  details: "MODIFY #ORD-2038: SL 2920 → 2930",       ip: "192.0.2.10" },
  { id: 8,  timestamp: isoOffset(86400), action: "login",           user: "admin",   details: "Admin login from dashboard",             ip: "192.0.2.1" },
  { id: 9,  timestamp: isoOffset(90000), action: "order_placed",    user: "trader",  details: "BUY INFY 1900 CE 2 lots @ MKT",          ip: "192.0.2.10" },
  { id: 10, timestamp: isoOffset(93600), action: "logout",          user: "trader",  details: "Session expired — auto logout",          ip: "192.0.2.10" },
];

export const ACTION_TYPES = [
  "order_placed",
  "order_cancelled",
  "order_modified",
  "position_closed",
  "settings_changed",
  "login",
  "logout",
] as const;
