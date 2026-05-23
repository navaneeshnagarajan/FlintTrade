/**
 * AuthFlowTOTP — credential form for brokers that use client ID, password,
 * and TOTP code authentication (auth_flow: "totp_form").
 */

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import type { BrokerInfo } from "@/types/broker";

interface AuthFlowTOTPProps {
  broker: BrokerInfo;
  onSubmit: (label: string, credentials: Record<string, string>) => void;
  onCancel: () => void;
  isLoading?: boolean;
}

export function AuthFlowTOTP({
  broker,
  onSubmit,
  onCancel,
  isLoading = false,
}: AuthFlowTOTPProps) {
  const [label, setLabel] = useState(`${broker.display_name} - Main`);
  const [clientId, setClientId] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit(label, { client_id: clientId, password, totp });
  };

  const canSubmit =
    clientId.trim().length > 0 &&
    password.trim().length > 0 &&
    totp.trim().length === 6 &&
    !isLoading;

  return (
    <form onSubmit={handleSubmit} className="space-y-4 max-w-md">
      <h3 className="font-medium text-text-primary">Connect {broker.display_name}</h3>

      <div className="space-y-1.5">
        <Label
          htmlFor="totp-label"
          className="text-text-secondary text-xs uppercase tracking-wider"
        >
          Account Label
        </Label>
        <Input
          id="totp-label"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          aria-label="Account label"
          className="h-9 text-sm bg-surface-base border-border-default text-text-primary"
        />
      </div>

      <div className="space-y-1.5">
        <Label
          htmlFor="totp-client-id"
          className="text-text-secondary text-xs uppercase tracking-wider"
        >
          Client ID
        </Label>
        <Input
          id="totp-client-id"
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          aria-label="Client ID"
          required
          autoComplete="username"
          className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
        />
      </div>

      <div className="space-y-1.5">
        <Label
          htmlFor="totp-password"
          className="text-text-secondary text-xs uppercase tracking-wider"
        >
          Password
        </Label>
        <Input
          id="totp-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          type="password"
          aria-label="Password"
          required
          autoComplete="current-password"
          className="h-9 text-sm bg-surface-base border-border-default text-text-primary"
        />
      </div>

      <div className="space-y-1.5">
        <Label
          htmlFor="totp-code"
          className="text-text-secondary text-xs uppercase tracking-wider"
        >
          TOTP Code
        </Label>
        <Input
          id="totp-code"
          value={totp}
          onChange={(e) => setTotp(e.target.value.replace(/\D/g, "").slice(0, 6))}
          aria-label="TOTP code"
          placeholder="6-digit code"
          required
          maxLength={6}
          inputMode="numeric"
          autoComplete="one-time-code"
          className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono tracking-widest"
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
