/**
 * AuthFlowAPIKey — credential form for brokers that use API key + secret
 * direct authentication (auth_flow: "api_key_direct").
 */

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import type { BrokerInfo } from "@/types/broker";

interface AuthFlowAPIKeyProps {
  broker: BrokerInfo;
  onSubmit: (label: string, credentials: Record<string, string>) => void;
  onCancel: () => void;
  isLoading?: boolean;
}

export function AuthFlowAPIKey({
  broker,
  onSubmit,
  onCancel,
  isLoading = false,
}: AuthFlowAPIKeyProps) {
  const [label, setLabel] = useState(`${broker.display_name} - Main`);
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit(label, { api_key: apiKey, api_secret: apiSecret });
  };

  const canSubmit = apiKey.trim().length > 0 && !isLoading;

  return (
    <form onSubmit={handleSubmit} className="space-y-4 max-w-md">
      <h3 className="font-medium text-text-primary">Connect {broker.display_name}</h3>

      <div className="space-y-1.5">
        <Label
          htmlFor="apikey-label"
          className="text-text-secondary text-xs uppercase tracking-wider"
        >
          Account Label
        </Label>
        <Input
          id="apikey-label"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          aria-label="Account label"
          className="h-9 text-sm bg-surface-base border-border-default text-text-primary"
        />
      </div>

      <div className="space-y-1.5">
        <Label
          htmlFor="apikey-key"
          className="text-text-secondary text-xs uppercase tracking-wider"
        >
          API Key
        </Label>
        <Input
          id="apikey-key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          type="password"
          aria-label="API key"
          required
          autoComplete="off"
          className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
        />
      </div>

      <div className="space-y-1.5">
        <Label
          htmlFor="apikey-secret"
          className="text-text-secondary text-xs uppercase tracking-wider"
        >
          API Secret
        </Label>
        <Input
          id="apikey-secret"
          value={apiSecret}
          onChange={(e) => setApiSecret(e.target.value)}
          type="password"
          aria-label="API secret"
          autoComplete="off"
          className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
        />
      </div>

      <div className="flex gap-2 pt-1">
        <Button type="submit" disabled={!canSubmit}>
          {isLoading ? "Connecting..." : "Connect"}
        </Button>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
