/**
 * ConnectionStep — connection configuration step in the setup wizard.
 *
 * Two modes toggled via tabs:
 *   - "FlintTrade Gateway" — pick a broker, enter credentials, manage accounts
 *   - "OpenAlgo Bridge"    — connect to an external OpenAlgo-compatible server
 *
 * Exports: ConnectionStep, ConnectionFormValues, deriveWsUrl
 */

import { useState, useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  CheckCircle,
  XCircle,
  Loader2,
  Wifi,
  ArrowRight,
  ArrowLeft,
  PlusCircle,
  CheckCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useConnectionStore } from "@/stores/connectionStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { ping } from "@/services/api";
import { useBrokerAuth } from "@/hooks/useBrokerAuth";
import { BrokerPicker } from "./BrokerPicker";
import { ConnectedAccounts } from "./ConnectedAccounts";
import { AuthFlowAPIKey } from "./AuthFlowAPIKey";
import { AuthFlowTOTP } from "./AuthFlowTOTP";
import type { BrokerInfo } from "@/types/broker";

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

export const connectionSchema = z.object({
  host: z.string().min(1, "Host is required").url("Must be a valid URL (include http://)"),
  apiKey: z.string().min(8, "API key must be at least 8 characters"),
  wsPort: z.string().min(1, "WebSocket port is required"),
});

export type ConnectionFormValues = z.infer<typeof connectionSchema>;

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

export function deriveWsUrl(host: string, wsPort: string): string {
  try {
    const url = new URL(host);
    const proto = url.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${url.hostname}:${wsPort}`;
  } catch {
    return `ws://localhost:${wsPort}`;
  }
}

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
      apiKey: defaultValues?.apiKey ?? "",
      wsPort: defaultValues?.wsPort ?? "8765",
    },
  });

  const [testState, setTestState] = useState<"idle" | "testing" | "ok" | "fail">("idle");
  const [testError, setTestError] = useState("");

  async function handleTest() {
    const vals = getValues();
    const wsUrl = deriveWsUrl(vals.host, vals.wsPort);
    useConnectionStore.getState().setConfig({ host: vals.host, apiKey: vals.apiKey, wsUrl });

    setTestState("testing");
    setTestError("");
    try {
      await ping();
      setTestState("ok");
    } catch (err) {
      setTestState("fail");
      setTestError(err instanceof Error ? err.message : "Connection failed");
    }
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
        {testState === "fail" && (
          <span className="flex items-center gap-1.5 text-red-400 text-sm">
            <XCircle className="size-4" />
            <span className="truncate max-w-50">{testError || "Failed"}</span>
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
  apiKey: "direct-connect",
  wsPort: "8765",
};

interface DirectConnectPanelProps {
  onComplete: (values: ConnectionFormValues) => void;
}

type DirectStep = "accounts" | "picking" | "auth";

function DirectConnectPanel({ onComplete }: DirectConnectPanelProps) {
  const { flowState, startFlow, submitCredentials, reset } = useBrokerAuth();
  const accounts = useBrokerStore((s) => s.accounts);
  const [directStep, setDirectStep] = useState<DirectStep>("accounts");
  const [selectedBroker, setSelectedBroker] = useState<BrokerInfo | null>(null);

  // Derive which auth sub-form to show from useBrokerAuth state
  const showAuthForm =
    flowState.step === "entering_credentials" ||
    flowState.step === "authenticating" ||
    flowState.step === "error";

  // When auth succeeds go back to accounts list (must be in useEffect, not render body)
  useEffect(() => {
    if (flowState.step === "success" && directStep === "auth") {
      setDirectStep("accounts");
      setSelectedBroker(null);
    }
  }, [flowState.step, directStep]);

  function handleBrokerSelect(broker: BrokerInfo) {
    setSelectedBroker(broker);
    startFlow(broker);
    setDirectStep("auth");
  }

  function handleAuthCancel() {
    reset();
    setSelectedBroker(null);
    setDirectStep("accounts");
  }

  const isAuthLoading = flowState.step === "authenticating";
  const authError = flowState.step === "error" ? flowState.message : undefined;

  // Accounts list view
  if (directStep === "accounts") {
    return (
      <div className="space-y-4">
        <ConnectedAccounts />

        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setDirectStep("picking")}
          className="w-full border-border-default text-text-secondary hover:text-text-primary"
        >
          <PlusCircle className="size-3.5 mr-1.5" />
          Add Broker Account
        </Button>

        <Button
          type="button"
          className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
          disabled={accounts.length === 0}
          onClick={() => onComplete(DIRECT_CONNECT_PLACEHOLDER)}
        >
          <CheckCheck className="size-4 mr-2" />
          {accounts.length === 0 ? "Connect at least one broker" : "Continue"}
          {accounts.length > 0 && <ArrowRight className="size-4 ml-2" />}
        </Button>
      </div>
    );
  }

  // Broker picker grid
  if (directStep === "picking") {
    return (
      <div className="space-y-4">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setDirectStep("accounts")}
          className="text-text-muted hover:text-text-primary -ml-1"
        >
          <ArrowLeft className="size-3.5 mr-1" /> Back
        </Button>

        <p className="text-xs text-text-secondary">Select a broker to connect</p>

        <div className="max-h-64 overflow-y-auto pr-1">
          <BrokerPicker onSelect={handleBrokerSelect} />
        </div>
      </div>
    );
  }

  // Auth form (api_key_direct or totp_form)
  if (directStep === "auth" && selectedBroker) {
    const broker = selectedBroker;

    return (
      <div className="space-y-4">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={handleAuthCancel}
          className="text-text-muted hover:text-text-primary -ml-1"
        >
          <ArrowLeft className="size-3.5 mr-1" /> Back to broker list
        </Button>

        {authError && (
          <p className="text-red-400 text-xs px-1">{authError}</p>
        )}

        {showAuthForm && broker.auth_flow === "api_key_direct" && (
          <AuthFlowAPIKey
            broker={broker}
            onSubmit={(label, creds) => void submitCredentials(label, creds)}
            onCancel={handleAuthCancel}
            isLoading={isAuthLoading}
          />
        )}

        {showAuthForm && broker.auth_flow === "totp_form" && (
          <AuthFlowTOTP
            broker={broker}
            onSubmit={(label, creds) => void submitCredentials(label, creds)}
            onCancel={handleAuthCancel}
            isLoading={isAuthLoading}
          />
        )}

        {!showAuthForm && (
          <p className="text-xs text-text-secondary py-4 text-center">
            Auth flow &ldquo;{broker.auth_flow}&rdquo; is not yet supported in the setup wizard.
            Use Settings &rarr; Accounts after setup.
          </p>
        )}
      </div>
    );
  }

  return null;
}

// ---------------------------------------------------------------------------
// ConnectionStep (public export)
// ---------------------------------------------------------------------------

interface ConnectionStepProps {
  onComplete: (values: ConnectionFormValues) => void;
  defaultValues?: Partial<ConnectionFormValues>;
}

export function ConnectionStep({ onComplete, defaultValues }: ConnectionStepProps) {
  const [mode, setMode] = useState<ConnectionMode>("direct");

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
          FlintTrade Gateway
        </TabButton>
      </div>

      {/* Mode description */}
      {mode === "openalgo" ? (
        <p className="text-xs text-text-muted">
          Connect to a running OpenAlgo-compatible server if you already use one.
        </p>
      ) : (
        <p className="text-xs text-text-muted">
          Connect directly to your broker using the FlintTrade gateway. No separate OpenAlgo setup needed.
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
          onClick={() => onComplete({ host: "", apiKey: "", wsPort: "8765" })}
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
