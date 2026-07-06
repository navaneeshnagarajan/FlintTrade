/**
 * Sample tape for demo/disconnected mode — a plausible RELIANCE minute.
 */

import type { TapePrint } from "./tape";

export const SAMPLE_TAPE: TapePrint[] = [
  { id: 20, time: "10:42:19", price: 2851.4, qty: 250, side: "buy" },
  { id: 19, time: "10:42:18", price: 2851.4, qty: 120, side: "buy" },
  { id: 18, time: "10:42:16", price: 2851.2, qty: 75, side: "sell" },
  { id: 17, time: "10:42:15", price: 2851.3, qty: 480, side: "buy" },
  { id: 16, time: "10:42:13", price: 2851.1, qty: 60, side: "sell" },
  { id: 15, time: "10:42:12", price: 2851.0, qty: 320, side: "sell" },
  { id: 14, time: "10:42:10", price: 2851.2, qty: 150, side: "buy" },
  { id: 13, time: "10:42:08", price: 2851.1, qty: 90, side: "sell" },
  { id: 12, time: "10:42:07", price: 2851.3, qty: 610, side: "buy" },
  { id: 11, time: "10:42:05", price: 2851.2, qty: 45, side: "sell" },
  { id: 10, time: "10:42:04", price: 2851.4, qty: 200, side: "buy" },
  { id: 9, time: "10:42:02", price: 2851.3, qty: 130, side: "sell" },
  { id: 8, time: "10:42:00", price: 2851.5, qty: 340, side: "buy" },
  { id: 7, time: "10:41:58", price: 2851.4, qty: 85, side: "sell" },
  { id: 6, time: "10:41:56", price: 2851.6, qty: 520, side: "buy" },
  { id: 5, time: "10:41:55", price: 2851.5, qty: 110, side: "sell" },
  { id: 4, time: "10:41:53", price: 2851.7, qty: 260, side: "buy" },
  { id: 3, time: "10:41:51", price: 2851.6, qty: 70, side: "sell" },
  { id: 2, time: "10:41:50", price: 2851.8, qty: 430, side: "buy" },
  { id: 1, time: "10:41:48", price: 2851.7, qty: 95, side: "neutral" },
];
