/**
 * ConnectionSection — broker gateway URL, API key, and WebSocket port settings.
 */

import { Loader2, Wifi, CheckCircle2, XCircle, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FieldRow, TextInput, SectionTitle } from "./shared";
import { useTestConnection } from "@/hooks/useTestConnection";
import { applyOpenAlgoRestPort } from "@/services/ftApi.openalgo";

interface ApiSettings {
  host: string;
  port: string;
  apiKey: string;
  wsPort: string;
}

interface ConnectionSectionProps {
  settings: ApiSettings;
  onChange: (field: keyof ApiSettings, value: string) => void;
}

export function ConnectionSection({ settings, onChange }: ConnectionSectionProps) {
  const { status: connStatus, message: connMessage, testConnection } = useTestConnection();

  const testing = connStatus === "testing";

  async function handleTestConnection() {
    await testConnection(applyOpenAlgoRestPort(settings.host, settings.port), settings.apiKey);
  }

  return (
    <div className="space-y-5">
      <SectionTitle>Broker Gateway</SectionTitle>

      <FieldRow
        label="Gateway URL"
        hint="Base URL for the OpenAlgo-compatible bridge — OpenAlgo serves on port 5000 by default (5100 is FlintTrade's own backend, not the bridge). Native broker connections are managed from Brokers."
      >
        <TextInput
          value={settings.host}
          onChange={(v) => onChange("host", v)}
          placeholder="http://127.0.0.1:5000"
          aria-label="Broker gateway URL"
        />
      </FieldRow>

      <FieldRow
        label="REST Port"
        hint="Used when Gateway URL omits an explicit port."
      >
        <TextInput
          value={settings.port}
          onChange={(v) => onChange("port", v)}
          placeholder="5000"
          aria-label="REST port"
        />
      </FieldRow>

      <FieldRow
        label="API Key"
        hint="API key for the selected broker bridge. Saved in the local FlintTrade workspace; existing saved keys are kept unless you enter a replacement."
      >
        <TextInput
          value={settings.apiKey}
          onChange={(v) => onChange("apiKey", v)}
          type="password"
          placeholder="••••••••••••••••"
          aria-label="Broker gateway API key"
        />
      </FieldRow>

      <FieldRow
        label="WebSocket Port"
        hint="Live-market WebSocket port. OpenAlgo-compatible gateways commonly use 8765."
      >
        <TextInput
          value={settings.wsPort}
          onChange={(v) => onChange("wsPort", v)}
          placeholder="8765"
          aria-label="WebSocket port"
        />
      </FieldRow>

      <div className="space-y-2">
        <button
          type="button"
          onClick={() => void handleTestConnection()}
          disabled={testing}
          className="flex items-center gap-2 px-4 py-1.5 text-xs font-medium rounded bg-accent/10 border border-accent/30 text-accent hover:bg-accent/20 hover:border-accent/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {testing ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Wifi size={12} />
          )}
          {testing ? "Testing..." : "Test Connection"}
        </button>

        {connStatus !== "idle" && connStatus !== "testing" && connMessage && (
          <div className={`flex items-center gap-2 px-3 py-2 rounded text-xs border ${
            connStatus === "ok"
              ? "bg-profit/10 border-profit/20 text-profit"
              : "bg-loss/10 border-loss/20 text-loss"
          }`}>
            {connStatus === "ok" ? (
              <CheckCircle2 size={13} />
            ) : (
              <XCircle size={13} />
            )}
            <span>{connMessage}</span>
          </div>
        )}
      </div>

      {/* Setup wizard entry point — the guided /setup flow configures the
          connection, trading defaults and risk limits in one pass. Navigation
          goes through the flinttrade:navigate event bus (handled by AppLayout)
          so this section stays usable outside a Router context. */}
      <div className="pt-4 border-t border-border-default space-y-2">
        <p className="text-xs text-text-muted">
          Prefer a guided flow? The setup wizard walks through connection, trading defaults and risk limits.
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            window.dispatchEvent(
              new CustomEvent("flinttrade:navigate", { detail: "/setup" }),
            )
          }
          className="border-border-default text-text-secondary hover:text-text-primary"
        >
          <Wand2 size={12} className="mr-1.5" aria-hidden="true" />
          Open setup wizard
        </Button>
      </div>
    </div>
  );
}
