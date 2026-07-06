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
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  connectionSchema,
  deriveWsUrl,
  type ConnectionFormValues,
} from "./connectionForm";
import {
  CheckCircle,
  XCircle,
  Loader2,
  Wifi,
  ArrowRight,
  CheckCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useConnectionStore } from "@/stores/connectionStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useBrokerAccounts } from "@/hooks/useBrokerAccounts";
import { useTestConnection } from "@/hooks/useTestConnection";
import { applyOpenAlgoRestPort } from "@/services/ftApi.openalgo";
import { BrokerConnect } from "@/components/account/BrokerConnect";
import type { BrokerAccount } from "@/types/broker";

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------


// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------


// ---------------------------------------------------------------------------
// Tab toggle
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// OpenAlgo-compatible bridge sub-panel
// ---------------------------------------------------------------------------

interface OpenAlgoFormProps {
  defaultValues?: Partial<ConnectionFormValues>;
  onComplete: (values: ConnectionFormValues) => void;
}

function OpenAlgoForm({ defaultValues, onComplete }: OpenAlgoFormProps) {
  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors },
  } = useForm<ConnectionFormValues>({
    resolver: zodResolver(connectionSchema),
    defaultValues: {
      host: defaultValues?.host ?? "http://localhost:5000",
      port: defaultValues?.port ?? "5000",
      apiKey: defaultValues?.apiKey ?? "",
      wsPort: defaultValues?.wsPort ?? "8765",
    },
  });

  const { status: testState, message: testMessage, testConnection } = useTestConnection();

  async function handleTest() {
    const vals = getValues();
    const wsUrl = deriveWsUrl(vals.host, vals.wsPort);
    useConnectionStore.getState().setConfig({ host: vals.host, apiKey: vals.apiKey, wsUrl });
    await testConnection(applyOpenAlgoRestPort(vals.host, vals.port), vals.apiKey);
  }

  return (
    <form onSubmit={handleSubmit(onComplete)} className="space-y-5">
      <div className="space-y-1.5">
        <Label htmlFor="host" className="text-text-secondary text-xs uppercase tracking-wider">
          OpenAlgo-Compatible URL
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="host"
            placeholder="http://localhost:5000"
            aria-label="OpenAlgo-compatible URL"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("host")}
          />
        </div>
        {errors.host && (
          <p className="text-red-400 text-xs">{errors.host.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="port" className="text-text-secondary text-xs uppercase tracking-wider">
          REST Port
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="port"
            placeholder="5000"
            aria-label="REST port"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("port")}
          />
        </div>
        {errors.port && (
          <p className="text-red-400 text-xs">{errors.port.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="apiKey" className="text-text-secondary text-xs uppercase tracking-wider">
          API Key
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="apiKey"
            type="password"
            autoComplete="off"
            placeholder="Your gateway API key"
            aria-label="OpenAlgo-compatible API key"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("apiKey")}
          />
        </div>
        {errors.apiKey && (
          <p className="text-red-400 text-xs">{errors.apiKey.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="wsPort" className="text-text-secondary text-xs uppercase tracking-wider">
          WebSocket Port
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="wsPort"
            placeholder="8765"
            aria-label="WebSocket port"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("wsPort")}
          />
        </div>
        {errors.wsPort && (
          <p className="text-red-400 text-xs">{errors.wsPort.message}</p>
        )}
      </div>

      <div className="flex items-center gap-3 pt-1">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void handleTest()}
          disabled={testState === "testing"}
          className="border-border-default text-text-secondary hover:text-text-primary"
        >
          {testState === "testing" ? (
            <Loader2 className="size-3.5 mr-1.5 animate-spin" />
          ) : (
            <Wifi className="size-3.5 mr-1.5" />
          )}
          Test Connection
        </Button>

        {testState === "ok" && (
          <span className="flex items-center gap-1.5 text-green-400 text-sm">
            <CheckCircle className="size-4" /> Connected
          </span>
        )}
        {testState === "error" && (
          <span className="flex items-center gap-1.5 text-red-400 text-sm">
            <XCircle className="size-4" />
            <span className="truncate max-w-50">{testMessage || "Failed"}</span>
          </span>
        )}
      </div>

      <Button
        type="submit"
        className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
      >
        Continue
        <ArrowRight className="size-4 ml-2" />
      </Button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Direct Connect sub-panel
// ---------------------------------------------------------------------------

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

interface DirectConnectPanelProps {
  onComplete: (values: ConnectionFormValues) => void;
}

function DirectConnectPanel({ onComplete }: DirectConnectPanelProps) {
  useBrokerAccounts();
  const hasWriteCapableBroker = useBrokerStore((s) => s.accounts.some(isWriteCapableBrokerAccount));

  return (
    <div className="space-y-4">
      <BrokerConnect />

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

// ---------------------------------------------------------------------------
// ConnectionStep (public export)
// ---------------------------------------------------------------------------

interface ConnectionStepProps {
  onComplete: (values: ConnectionFormValues) => void;
  defaultValues?: Partial<ConnectionFormValues>;
}

export function ConnectionStep({ onComplete, defaultValues }: ConnectionStepProps) {
  // OpenAlgo is the primary, community-tested connect path (principle 2), so it
  // is the default tab; native FlintTrade adapters are the secondary option.
  const [mode, setMode] = useState<ConnectionMode>("openalgo");

  return (
    <div className="space-y-5">
      {/* Mode toggle */}
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

      {/* Mode description */}
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

      {/* Active panel */}
      {mode === "openalgo" ? (
        <OpenAlgoForm defaultValues={defaultValues} onComplete={onComplete} />
      ) : (
        <DirectConnectPanel onComplete={onComplete} />
      )}

      {/* Skip / connect later */}
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
