/**
 * ConnectionSection — broker gateway URL, API key, and WebSocket port settings.
 */

import { Loader2, Wifi, CheckCircle2, XCircle } from "lucide-react";
import { FieldRow, TextInput, SectionTitle } from "./shared";
import { useTestConnection } from "@/hooks/useTestConnection";

interface ApiSettings {
  host: string;
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
    await testConnection(settings.host, settings.apiKey);
  }

  return (
    <div className="space-y-5">
      <SectionTitle>Broker Gateway</SectionTitle>

      <FieldRow
        label="Gateway URL"
        hint="Base URL for the OpenAlgo-compatible bridge. Native broker connections are managed from Brokers."
      >
        <TextInput
          value={settings.host}
          onChange={(v) => onChange("host", v)}
          placeholder="http://127.0.0.1:5100"
          aria-label="Broker gateway URL"
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
    </div>
  );
}
