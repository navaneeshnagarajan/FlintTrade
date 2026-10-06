/**
 * ConnectionStep — optional broker step in the setup wizard.
 *
 * Monday primary path (FT-MONDAY-001): continue without a broker. Practice
 * fills use FlintTrade's native SandboxEngine. Native brokers
 * stay Settings/fallback only — never the primary connect CTA.
 *
 * Exports: ConnectionStep (schema/helpers live in connectionForm.ts for Fast Refresh)
 */

import { useState } from "react";
import { ArrowRight, CheckCheck, Info } from "lucide-react";

import { BrokerConnect } from "@/components/account/BrokerConnect";
import { Button } from "@/components/ui/button";
import { useBrokerStore } from "@/stores/brokerStore";
import type { BrokerAccount } from "@/types/broker";
import type { ConnectionFormValues } from "./connectionForm";
import {
  CONNECTED_READ_LABEL,
  NEO_OPERATOR_COPY,
  isMondayReadBroker,
} from "@/lib/connectedReadChrome";

type ConnectionMode = "direct";

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
          ? "bg-accent text-accent-foreground"
          : "text-text-secondary hover:text-text-primary",
      ].join(" ")}
      aria-pressed={active}
    >
      {children}
    </button>
  );
}

function isWriteCapableBrokerAccount(account: BrokerAccount): boolean {
  return account.source === "native" && account.status === "connected" && account.read_only !== true;
}

function isMondayReadConnectedAccount(account: BrokerAccount): boolean {
  return (
    account.source === "native"
    && account.status === "connected"
    && isMondayReadBroker(account.broker)
    && account.read_smoke_ok === true
  );
}

function isReadOnlyConnectedBrokerAccount(account: BrokerAccount): boolean {
  return account.source === "native" && account.status === "connected" && account.read_only === true;
}

interface DirectConnectPanelProps {
  onComplete: (values: ConnectionFormValues) => void;
}

function DirectConnectPanel({ onComplete }: DirectConnectPanelProps) {
  const hasWriteCapableBroker = useBrokerStore((state) =>
    state.accounts.some(isWriteCapableBrokerAccount),
  );
  const hasMondayReadBroker = useBrokerStore((state) =>
    state.accounts.some(isMondayReadConnectedAccount),
  );
  const hasReadOnlyConnectedBroker = useBrokerStore((state) =>
    state.accounts.some(isReadOnlyConnectedBrokerAccount),
  );
  const canContinue = hasMondayReadBroker || hasWriteCapableBroker;

  return (
    <div className="space-y-4">
      <BrokerConnect />

      {hasMondayReadBroker && (
        <div
          role="note"
          className="flex items-start gap-2 px-3 py-2 rounded border border-amber-500/30 bg-amber-500/10 text-xs text-amber-400"
        >
          <Info className="size-3.5 mt-0.5 shrink-0" aria-hidden="true" />
          <span>
            {CONNECTED_READ_LABEL} only — never placeable Live orders.
            Neo has no sandbox. {NEO_OPERATOR_COPY}
          </span>
        </div>
      )}

      {!hasWriteCapableBroker && !hasMondayReadBroker && hasReadOnlyConnectedBroker && (
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
        disabled={!canContinue}
        onClick={() => onComplete({ brokerConnected: true })}
      >
        <CheckCheck className="size-4 mr-2" />
        {canContinue ? "Continue" : "Connect Dhan or Neo for Connected (read)"}
        {canContinue && <ArrowRight className="size-4 ml-2" />}
      </Button>
    </div>
  );
}

interface ConnectionStepProps {
  onComplete: (values: ConnectionFormValues) => void;
  /**
   * Brokerless continuation on the Practice desk tray. When set, the primary
   * control records a skip instead of a successful connection. The first-run
   * wizard omits it and still advances through `onComplete`.
   */
  onContinueWithoutBroker?: () => void;
  defaultValues?: Partial<ConnectionFormValues>;
}

export function ConnectionStep({
  onComplete,
  onContinueWithoutBroker,
}: ConnectionStepProps) {
  const [mode, setMode] = useState<ConnectionMode | null>(null);

  function continueWithoutBroker() {
    if (onContinueWithoutBroker) {
      onContinueWithoutBroker();
      return;
    }
    onComplete({ brokerConnected: false });
  }

  return (
    <div className="space-y-5">
      <div className="space-y-3">
        <p className="text-sm text-text-primary">
          Practice — simulated fills, no real money. You do not
          need a broker for Practice.
        </p>
        <Button
          type="button"
          className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
          onClick={continueWithoutBroker}
        >
          Continue without a broker
          <ArrowRight className="size-4 ml-2" />
        </Button>
        <p className="text-xs text-text-muted text-center">
          Native brokers stay in Settings as a fallback — not the
          primary Practice path.
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
          <TabButton active={mode === "direct"} onClick={() => setMode("direct")}>
            FlintTrade Native
          </TabButton>
        </div>

        {mode === "direct" && (
          <p className="text-xs text-text-muted">
            Native Dhan + Kotak Neo stays {CONNECTED_READ_LABEL}. Successful
            non-funded reads never become placeable Live orders. Neo has no
            Practice sandbox. {NEO_OPERATOR_COPY}
          </p>
        )}

        {mode === "direct" && <DirectConnectPanel onComplete={onComplete} />}
      </div>
    </div>
  );
}
