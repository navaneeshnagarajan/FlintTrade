/**
 * Reserved status slot for a stop-loss that triggered and did not fill.
 * "Exit now" opens a limit ticket; it never sends an order itself.
 */

import { Button } from "@/components/ui/button";
import {
  EXIT_NOW,
  STOP_LOSS_NOT_FILLED,
  openExitTicket,
  type ExitTicket,
} from "@/lib/stopLossState";

interface StopLossNotFilledChipProps {
  symbol: string;
  /** Built at click time so it reads the latest position and price. */
  ticket: () => ExitTicket | null;
  textClassName?: string;
}

export function StopLossNotFilledChip({ symbol, ticket, textClassName = "text-xxs" }: StopLossNotFilledChipProps) {
  return (
    <span className="inline-flex items-center gap-1" data-testid="stop-loss-not-filled" role="status">
      <span className={`${textClassName} font-medium text-loss`}>{STOP_LOSS_NOT_FILLED}</span>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-6 px-2 text-[13px] leading-4 border-loss/60 text-loss hover:bg-loss/10"
        aria-label={`${EXIT_NOW} ${symbol}`}
        onClick={() => {
          const next = ticket();
          if (next) openExitTicket(next);
        }}
      >
        {EXIT_NOW}
      </Button>
    </span>
  );
}
