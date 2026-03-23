/**
 * ConnectionSection — OpenAlgo host, API key, and WebSocket port settings.
 */

import { useState } from "react";
import { Loader2, Wifi, CheckCircle2, XCircle } from "lucide-react";
import { ping } from "@/services/api";
import { FieldRow, TextInput, SectionTitle } from "./shared";

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
  const [testing, setTesting]         = useState(false);
  const [connStatus, setConnStatus]   = useState<"connected" | "failed" | null>(null);
  const [connMessage, setConnMessage] = useState("");

  async function handleTestConnection() {
    setTesting(true);
    setConnStatus(null);
    setConnMessage("");
    try {
      await ping();
      setConnStatus("connected");
      setConnMessage("OpenAlgo is reachable and responding.");
    } catch (e) {
      setConnStatus("failed");
      setConnMessage(e instanceof Error ? e.message : "Connection failed. Check host and API key.");
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-5">
      <SectionTitle>API Connection</SectionTitle>

      <FieldRow
        label="OpenAlgo Host"
        hint="Base URL of your OpenAlgo instance. Set VITE_OPENALGO_HOST in .env to override at build time."
      >
        <TextInput
          value={settings.host}
          onChange={(v) => onChange("host", v)}
          placeholder="http://127.0.0.1:5000"
          aria-label="OpenAlgo host"
        />
      </FieldRow>

      <FieldRow
        label="API Key"
        hint="Your OpenAlgo API key. Stored in localStorage — do not use on shared machines."
      >
        <TextInput
          value={settings.apiKey}
          onChange={(v) => onChange("apiKey", v)}
          type="password"
          placeholder="••••••••••••••••"
          aria-label="OpenAlgo API key"
        />
      </FieldRow>

      <FieldRow
        label="WebSocket Port"
        hint="OpenAlgo WebSocket port (default 8765). Used for live tick data."
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
          {testing ? "Testing…" : "Test Connection"}
        </button>

        {connStatus && (
          <div className={`flex items-center gap-2 px-3 py-2 rounded text-xs border ${
            connStatus === "connected"
              ? "bg-profit/10 border-profit/20 text-profit"
              : "bg-loss/10 border-loss/20 text-loss"
          }`}>
            {connStatus === "connected" ? (
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
