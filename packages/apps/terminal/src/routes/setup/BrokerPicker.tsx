/**
 * BrokerPicker — grid of broker cards for selecting which broker to connect.
 * Used in the setup wizard broker selection step.
 */

import { Loader2 } from "lucide-react";
import { useBrokerList } from "@/hooks/useBrokerList";
import type { BrokerInfo } from "@/types/broker";

interface BrokerPickerProps {
  onSelect: (broker: BrokerInfo) => void;
}

export function BrokerPicker({ onSelect }: BrokerPickerProps) {
  const { data: brokers, isLoading } = useBrokerList();

  if (isLoading) {
    return (
      <div className="flex justify-center p-8">
        <Loader2 className="animate-spin" />
      </div>
    );
  }

  if (!brokers || brokers.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground text-sm">
        No brokers available. Ensure the gateway service is running.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
      {brokers.map((broker) => (
        <button
          key={broker.name}
          onClick={() => onSelect(broker)}
          className="text-left p-3 rounded-lg border border-border-default hover:border-accent/50 hover:bg-accent/5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
          aria-label={`Select ${broker.display_name}`}
        >
          <p className="font-medium text-sm text-text-primary">{broker.display_name}</p>
          <p className="text-xs text-text-secondary mt-1">{broker.exchanges.join(", ")}</p>
          <p className="text-[10px] text-text-muted mt-1 capitalize">
            {broker.auth_flow.replace(/_/g, " ")}
          </p>
        </button>
      ))}
    </div>
  );
}
