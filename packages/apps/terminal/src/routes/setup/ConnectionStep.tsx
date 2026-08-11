/**
 * ConnectionStep — connection configuration step in the setup wizard.
 *
 * Two modes toggled via tabs:
 *   - "OpenAlgo Bridge"    — connect to an external OpenAlgo-compatible server (primary)
 *   - "FlintTrade Native"  — use the catalogue-driven native broker surface
 *
 * Exports: ConnectionStep (schema/helpers live in connectionForm.ts for Fast Refresh)
 */

import { useState } from "react";
import { ArrowRight, CheckCheck, Info } from "lucide-react";

import { BrokerConnect } from "@/components/account/BrokerConnect";
import { OpenAlgoConnectionForm } from "@/components/account/OpenAlgoConnectionForm";
import { Button } from "@/components/ui/button";
import { useBrokerStore } from "@/stores/brokerStore";
import type { BrokerAccount } from "@/types/broker";
import type { ConnectionFormValues } from "./connectionForm";

type ConnectionMode = "openalgo" | "direct";

interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function TabButton({ active, onClick, children }: TabButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "flex-1 py-1.5 text-xs font-medium rounded-md transition-colors",
        active
          ? "bg-accent text-white"
          : "text-text-secondary hover:text-text-primary",
      ].join(" ")}
      aria-pressed={active}
    >
      {children}
    </button>
  );
}

/**
 * Synthetic ConnectionFormValues used when proceeding from Direct Connect.
 * Host/key are left as placeholder values — the gateway adapter handles auth
 * independently and the actual broker sessions live in brokerStore.
 */
const DIRECT_CONNECT_PLACEHOLDER: ConnectionFormValues = {
  host: "http://127.0.0.1:5100",
  port: "5100",
  apiKey: "direct-connect",
  wsPort: "8765",
};

function isWriteCapableBrokerAccount(account: BrokerAccount): boolean {
  return account.status === "connected" && account.read_only !== true;
}

function isReadOnlyConnectedBrokerAccount(account: BrokerAccount): boolean {
  return account.status === "connected" && account.read_only === true;
}

interface DirectConnectPanelProps {
  onComplete: (values: ConnectionFormValues) => void;
}

function DirectConnectPanel({ onComplete }: DirectConnectPanelProps) {
  const hasWriteCapableBroker = useBrokerStore((state) =>
    state.accounts.some(isWriteCapableBrokerAccount),
  );
  const hasReadOnlyConnectedBroker = useBrokerStore((state) =>
    state.accounts.some(isReadOnlyConnectedBrokerAccount),
  );

  return (
    <div className="space-y-4">
      <BrokerConnect />

      {!hasWriteCapableBroker && hasReadOnlyConnectedBroker && (
        <div
          role="note"
          className="flex items-start gap-2 px-3 py-2 rounded border border-amber-500/30 bg-amber-500/10 text-xs text-amber-400"
        >
          <Info className="size-3.5 mt-0.5 shrink-0" aria-hidden="true" />
          <span>
            A connected account is read-only: its broker session lacks order-placement
            authorisation, so it was demoted from write routing and cannot place orders.
            Re-authenticate it with trading permissions enabled, or connect a different broker.
          </span>
        </div>
      )}

      <Button
        type="button"
        className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
        disabled={!hasWriteCapableBroker}
        onClick={() => onComplete(DIRECT_CONNECT_PLACEHOLDER)}
      >
        <CheckCheck className="size-4 mr-2" />
        {hasWriteCapableBroker ? "Continue" : "Connect a write-capable broker"}
        {hasWriteCapableBroker && <ArrowRight className="size-4 ml-2" />}
      </Button>
    </div>
  );
}

interface ConnectionStepProps {
  onComplete: (values: ConnectionFormValues) => void;
  defaultValues?: Partial<ConnectionFormValues>;
}

export function ConnectionStep({ onComplete, defaultValues }: ConnectionStepProps) {
  // OpenAlgo is the primary, community-tested connect path, so it remains the
  // default tab; native FlintTrade adapters are the secondary option.
  const [mode, setMode] = useState<ConnectionMode>("openalgo");

  return (
    <div className="space-y-5">
      <div
        className="flex gap-1 p-1 rounded-lg bg-surface-base border border-border-default"
        role="tablist"
        aria-label="Connection mode"
      >
        <TabButton active={mode === "openalgo"} onClick={() => setMode("openalgo")}>
          OpenAlgo Bridge
        </TabButton>
        <TabButton active={mode === "direct"} onClick={() => setMode("direct")}>
          FlintTrade Native
        </TabButton>
      </div>

      {mode === "openalgo" ? (
        <p className="text-xs text-text-muted">
          <strong className="text-text-secondary">Recommended.</strong> Connect through OpenAlgo — 30+
          community-tested brokers, the battle-tested path.
        </p>
      ) : (
        <p className="text-xs text-text-muted">
          Connect a FlintTrade native adapter directly. Availability and login fields come from the
          broker catalogue. Secondary path — native order placement is not fully live-tested; use at
          your own risk.
        </p>
      )}

      {mode === "openalgo" ? (
        <OpenAlgoConnectionForm defaultValues={defaultValues} onSaved={onComplete} />
      ) : (
        <DirectConnectPanel onComplete={onComplete} />
      )}

      <div className="pt-2 border-t border-border-default space-y-2">
        <button
          type="button"
          onClick={() => onComplete({ host: "", port: "5000", apiKey: "", wsPort: "8765" })}
          className="w-full text-xs text-text-muted hover:text-text-primary transition-colors py-1.5 rounded focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          I&apos;ll connect later →
        </button>
        <p className="text-xs text-text-muted text-center">
          You can connect your broker anytime from Settings &rarr; Broker Gateway.
        </p>
      </div>
    </div>
  );
}
