/**
 * BrokerRequiredNotice: neutral one-line prompt for data that needs a
 * connected broker.
 *
 * "No broker connected" is a setup state, not a failure, so widgets render
 * this in place of their red error text when the backend refuses a read for
 * that reason. Every other error keeps the widget's own error styling.
 */

import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/Callout";
import { cn } from "@/lib/utils";

const BROKER_REQUIRED_PATTERN = /connected native broker account is required/i;

/** True when an error (or its message) is the backend's "connect a broker" refusal. */
export function isBrokerRequiredMessage(message: unknown): boolean {
  const text =
    typeof message === "string"
      ? message
      : message instanceof Error
        ? message.message
        : "";
  return BROKER_REQUIRED_PATTERN.test(text);
}

export interface BrokerRequiredNoticeProps {
  /** What the broker would load, e.g. "the option chain" or "expiries". */
  what: string;
  className?: string;
}

export function BrokerRequiredNotice({ what, className }: BrokerRequiredNoticeProps) {
  return (
    <Callout
      tone="neutral"
      data-testid="broker-required-notice"
      className={cn("items-center gap-2 rounded-md px-2 py-1 text-xs", className)}
      action={
        <Button
          type="button"
          variant="link"
          size="sm"
          className="h-auto px-0 py-0 text-xs"
          onClick={() => {
            window.dispatchEvent(new CustomEvent("flinttrade:navigate", { detail: "/brokers" }));
          }}
        >
          Open Brokers
        </Button>
      }
    >
      Connect a broker to load {what}.
    </Callout>
  );
}

export default BrokerRequiredNotice;
