/**
 * ConnectionStep — connection configuration step in the setup wizard.
 *
 * Two modes toggled via tabs:
 *   - "FlintTrade Gateway" — connect a NATIVE broker (Dhan / Upstox / Kotak Neo
 *     / INDmoney) with its real login method. This reuses the same working
 *     native flow as Settings → Brokers, so OAuth (Upstox) and the direct
 *     token / TOTP methods behave identically here. Brokers without a native
 *     adapter yet are shown as "coming soon".
 *   - "OpenAlgo Bridge"    — connect to an external OpenAlgo-compatible server.
 *
 * Exports: ConnectionStep, ConnectionFormValues, deriveWsUrl
 */

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle,
  XCircle,
  Loader2,
  Wifi,
  ArrowRight,
  CheckCheck,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { useConnectionStore } from "@/stores/connectionStore";
import { ping } from "@/services/api";
import { gatewayApi } from "@/services/gatewayApi";
import { listNativeAccounts } from "@/services/ftApi.native";
import { BrokersSection } from "@/tools/Settings/BrokersSection";

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
// Direct Connect sub-panel — native broker flow (reuses Settings → Brokers)
// ---------------------------------------------------------------------------

/**
 * Synthetic ConnectionFormValues used when proceeding from Direct Connect.
 * Host/key are placeholders — the native gateway handles auth independently and
 * the real sessions live in the backend vault, queried via /native/accounts.
 */
const DIRECT_CONNECT_PLACEHOLDER: ConnectionFormValues = {
  host: "http://127.0.0.1:5100",
  apiKey: "direct-connect",
  wsPort: "8765",
};

// Adapter ids that FlintTrade connects natively today. Anything catalogued for
// the OpenAlgo bridge but NOT in this set has no native adapter yet, so it is
// surfaced as "coming soon" rather than as a broken native option. ``kotak``
// (Kotak Securities, a bridge-only entry) is excluded from the coming-soon list
// too, to avoid confusion with the native ``kotakneo`` (Kotak Neo).
const NATIVE_ADAPTER_IDS = new Set(["dhan", "upstox", "kotakneo", "kotak", "indmoney"]);

/** A muted roster of brokers catalogued but not yet connectable natively. */
function ComingSoonBrokers() {
  const bridgeQuery = useQuery({
    queryKey: ["gateway", "brokers"],
    queryFn: gatewayApi.listBrokers,
    staleTime: 60 * 60 * 1000,
    retry: false,
  });

  const names = (bridgeQuery.data ?? [])
    .filter((b) => !NATIVE_ADAPTER_IDS.has(b.name))
    .map((b) => b.display_name);

  if (names.length === 0) return null;

  return (
    <div className="rounded-lg border border-border-default bg-surface-base p-3 space-y-2">
      <div className="flex items-center gap-1.5 text-xs text-text-secondary">
        <Sparkles className="size-3.5" /> More brokers — coming soon
      </div>
      <div className="flex flex-wrap gap-1.5">
        {names.map((name) => (
          <Badge
            key={name}
            variant="outline"
            className="text-[11px] text-text-muted opacity-70"
          >
            {name}
          </Badge>
        ))}
      </div>
      <p className="text-[11px] text-text-muted">
        Already run OpenAlgo? These connect today via the OpenAlgo Bridge tab above.
      </p>
    </div>
  );
}

interface DirectConnectPanelProps {
  onComplete: (values: ConnectionFormValues) => void;
}

function DirectConnectPanel({ onComplete }: DirectConnectPanelProps) {
  // Shares the ["native","accounts"] query cache with BrokersSection, so a
  // successful connect there flips the Continue button on immediately. Gate on a
  // LIVE session, not a mere stored row — re-running setup after the daily token
  // expired would otherwise count a dead account (has_session:false /
  // needs_relogin:true) as connected and let the operator advance with no
  // working broker session.
  const accountsQuery = useQuery({ queryKey: ["native", "accounts"], queryFn: listNativeAccounts });
  const connectedCount = (accountsQuery.data ?? []).filter(
    (a) => a.has_session && a.needs_relogin !== true,
  ).length;

  return (
    <div className="space-y-5">
      {/* The proven native connect UI — Dhan / Upstox / Kotak Neo / INDmoney. */}
      <BrokersSection />

      <ComingSoonBrokers />

      <Button
        type="button"
        className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
        disabled={connectedCount === 0}
        onClick={() => onComplete(DIRECT_CONNECT_PLACEHOLDER)}
      >
        <CheckCheck className="size-4 mr-2" />
        {connectedCount === 0 ? "Connect at least one broker to continue" : "Continue"}
        {connectedCount > 0 && <ArrowRight className="size-4 ml-2" />}
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
          You can connect your broker anytime from Settings &rarr; Brokers.
        </p>
      </div>
    </div>
  );
}
