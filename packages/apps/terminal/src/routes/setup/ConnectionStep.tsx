/**
 * ConnectionStep — optional broker step in the setup wizard.
 *
 * Monday primary path (FT-MONDAY-001): continue without a broker. Practice
 * fills use FlintTrade's native SandboxEngine. OpenAlgo and native brokers
 * stay Settings/fallback only — never the primary connect CTA.
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
  const [mode, setMode] = useState<ConnectionMode | null>(null);

  return (
    <div className="space-y-5">
      <div className="space-y-3">
        <p className="text-sm text-text-primary">
          Practice uses FlintTrade&apos;s SandboxEngine for paper fills. You do not
          need a broker for Monday Practice.
        </p>
        <Button
          type="button"
          className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
          onClick={() => onComplete({ host: "", port: "5000", apiKey: "", wsPort: "8765" })}
        >
          Continue without a broker
          <ArrowRight className="size-4 ml-2" />
        </Button>
        <p className="text-xs text-text-muted text-center">
          OpenAlgo and native brokers stay in Settings as a fallback — not the
          primary Monday path.
        </p>
      </div>

      <div className="pt-2 border-t border-border-default space-y-3">
        <p className="text-xs text-text-muted">
          Optional broker connection (Settings fallback)
        </p>
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

        {mode === "openalgo" && (
          <p className="text-xs text-text-muted">
            Settings fallback only — not the Monday primary connect path. Practice
            fills still use the native SandboxEngine.
          </p>
        )}
        {mode === "direct" && (
          <p className="text-xs text-text-muted">
            Connect a FlintTrade native adapter directly. Availability and login fields come from the
            broker catalogue. Secondary path — native order placement is not fully live-tested; use at
            your own risk.
          </p>
        )}

        {mode === "openalgo" ? (
          <OpenAlgoConnectionForm defaultValues={defaultValues} onSaved={onComplete} />
        ) : mode === "direct" ? (
          <DirectConnectPanel onComplete={onComplete} />
        ) : null}
      </div>
    </div>
  );
}
