/**
 * BrokerPicker — compatibility wrapper for the unified broker connect surface.
 *
 * Older setup code selected a broker from a broad catalogue card grid here.
 * Keep the export name for any stale imports, but route everything through
 * BrokerConnect so native connectability, MCP setup, OpenAlgo gateway accounts,
 * and vault-backed login methods stay on the single broker surface.
 */

import { BrokerConnect } from "@/components/account/BrokerConnect";
import type { BrokerInfo } from "@/types/broker";

interface BrokerPickerProps {
  onSelect: (broker: BrokerInfo) => void;
}

export function BrokerPicker(_props: BrokerPickerProps) {
  return <BrokerConnect />;
}
