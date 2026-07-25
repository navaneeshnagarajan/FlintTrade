/**
 * Sample tape for demo/disconnected mode — a plausible RELIANCE minute.
 *
 * Fixed prints, not generated ones: the widget must never animate invented
 * ticks behind a live-looking surface. The timestamps are derived from the
 * printed times against one fixed session date so the microstructure
 * statistics computed over this tape are the real statistics OF this tape.
 */

import type { TapePrint, TapeSide } from "./tape";

/** Midnight of the sample session, local time. */
const SAMPLE_SESSION_START = new Date(2026, 6, 6, 0, 0, 0, 0).getTime();

/** Epoch ms for an HH:MM:SS time within the sample session. */
function at(time: string): number {
  const [hours, minutes, seconds] = time.split(":").map(Number);
  return SAMPLE_SESSION_START + ((hours * 60 + minutes) * 60 + seconds) * 1_000;
}

type SampleRow = readonly [time: string, price: number, qty: number, side: TapeSide];

/** Newest first, matching the order the live tape is kept in. */
const SAMPLE_ROWS: readonly SampleRow[] = [
  ["10:42:19", 2851.4, 250, "buy"],
  ["10:42:18", 2851.4, 120, "buy"],
  ["10:42:16", 2851.2, 75, "sell"],
  ["10:42:15", 2851.3, 480, "buy"],
  ["10:42:13", 2851.1, 60, "sell"],
  ["10:42:12", 2851.0, 320, "sell"],
  ["10:42:10", 2851.2, 150, "buy"],
  ["10:42:08", 2851.1, 90, "sell"],
  ["10:42:07", 2851.3, 610, "buy"],
  ["10:42:05", 2851.2, 45, "sell"],
  ["10:42:04", 2851.4, 200, "buy"],
  ["10:42:02", 2851.3, 130, "sell"],
  ["10:42:00", 2851.5, 340, "buy"],
  ["10:41:58", 2851.4, 85, "sell"],
  ["10:41:56", 2851.6, 520, "buy"],
  ["10:41:55", 2851.5, 110, "sell"],
  ["10:41:53", 2851.7, 260, "buy"],
  ["10:41:51", 2851.6, 70, "sell"],
  ["10:41:50", 2851.8, 430, "buy"],
  ["10:41:48", 2851.7, 95, "neutral"],
];

export const SAMPLE_TAPE: TapePrint[] = SAMPLE_ROWS.map(
  ([time, price, qty, side], index) => ({
    id: SAMPLE_ROWS.length - index,
    ts: at(time),
    time,
    price,
    qty,
    side,
  }),
);

/**
 * The instant the sample tape's statistics are measured from — one second past
 * its newest print, so the demo statistics describe the demo tape rather than
 * decaying to zero against the wall clock.
 */
export const SAMPLE_TAPE_NOW: number = SAMPLE_TAPE[0].ts + 1_000;
