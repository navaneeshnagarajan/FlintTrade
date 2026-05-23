/**
 * Sample data for PivotPointsWidget — explore/disconnected mode.
 * Values are illustrative only, not real market data.
 */

export interface PrevDayOHLC {
  high: number;
  low: number;
  close: number;
  open?: number;
}

export const SAMPLE_PREV_DAY: PrevDayOHLC = {
  high: 22580,
  low: 22210,
  close: 22450,
  open: 22310,
};

export const SAMPLE_CURRENT_PRICE = 22495;
