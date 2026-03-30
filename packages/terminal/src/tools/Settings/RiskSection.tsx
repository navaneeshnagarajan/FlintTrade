/**
 * RiskSection — MTM stoploss, MTM target, max position lots, max orders per minute.
 *
 * Saves locally to Zustand (client-side enforcement) and syncs to the
 * FlintTrade backend via POST /ft-api/api/v1/safety/config so the 5-layer
 * safety system also picks up the limits.
 */

import { useState, useCallback } from "react";
import { useMutation } from "@tanstack/react-query";
import { RefreshCw, Save, CheckCircle2, AlertTriangle } from "lucide-react";
import { FieldRow, TextInput, SectionTitle } from "./shared";
import { Button } from "@/components/ui/button";
import { RISK_HINTS } from "@/lib/schemas/riskSchema";
import { updateSafetyConfig } from "@/services/ftApi";

interface RiskSettings {
  maxPositionLots: string;
  mtmStoploss: string;
  mtmTarget: string;
  maxOrdersPerMinute: string;
}

interface RiskSectionProps {
  settings: RiskSettings;
  onChange: (field: keyof RiskSettings, value: string) => void;
}

export function RiskSection({ settings, onChange }: RiskSectionProps) {
  const [syncStatus, setSyncStatus] = useState<"idle" | "success" | "error">("idle");

  const syncMutation = useMutation({
    mutationFn: () => {
      const maxPos = parseFloat(settings.maxPositionLots);
      const mtmSl  = parseFloat(settings.mtmStoploss);
      const mtmTgt = parseFloat(settings.mtmTarget);

      return updateSafetyConfig({
        max_positions: isNaN(maxPos) ? 0 : maxPos,
        daily_loss_kill_pct: isNaN(mtmSl) ? 0 : Math.abs(mtmSl),
        daily_loss_pause_pct: isNaN(mtmTgt) ? 0 : mtmTgt,
      });
    },
    onSuccess: () => {
      setSyncStatus("success");
      setTimeout(() => setSyncStatus("idle"), 3000);
    },
    onError: () => {
      setSyncStatus("error");
      setTimeout(() => setSyncStatus("idle"), 5000);
    },
  });

  const handleSync = useCallback(() => {
    syncMutation.mutate();
  }, [syncMutation]);

  return (
    <div className="space-y-5">
      <SectionTitle>Risk Limits</SectionTitle>

      <div className="p-3 rounded bg-warning/5 border border-warning/20 text-xs text-warning/80">
        Risk limits are enforced client-side only. They do NOT replace broker-level risk controls.
        Always configure limits at the broker or OpenAlgo level as your primary protection.
      </div>

      <FieldRow
        label="Max Position Size (lots)"
        hint="Maximum number of lots per position. Leave blank to disable."
        tooltip={RISK_HINTS.maxPositionLots}
      >
        <TextInput
          value={settings.maxPositionLots}
          onChange={(v) => onChange("maxPositionLots", v)}
          placeholder="e.g. 10"
          type="number"
          aria-label="Maximum position size in lots"
        />
      </FieldRow>

      <FieldRow
        label="MTM Stoploss (₹)"
        hint="Mark-to-market loss limit. Enter as negative number (e.g. -5000). Leave blank to disable."
        tooltip={RISK_HINTS.mtmStoploss}
      >
        <TextInput
          value={settings.mtmStoploss}
          onChange={(v) => onChange("mtmStoploss", v)}
          placeholder="e.g. -5000"
          type="number"
          aria-label="MTM stoploss in rupees"
        />
      </FieldRow>

      <FieldRow
        label="MTM Target (₹)"
        hint="Mark-to-market profit target. Leave blank to disable."
        tooltip={RISK_HINTS.mtmTarget}
      >
        <TextInput
          value={settings.mtmTarget}
          onChange={(v) => onChange("mtmTarget", v)}
          placeholder="e.g. 10000"
          type="number"
          aria-label="MTM profit target in rupees"
        />
      </FieldRow>

      <FieldRow
        label="Max Orders per Minute"
        hint="Rate limit for order placement. Leave blank to use OpenAlgo default (10/sec)."
        tooltip={RISK_HINTS.maxOrdersPerMinute}
      >
        <TextInput
          value={settings.maxOrdersPerMinute}
          onChange={(v) => onChange("maxOrdersPerMinute", v)}
          placeholder="e.g. 20"
          type="number"
          aria-label="Maximum orders per minute"
        />
      </FieldRow>

      {/* Sync to backend button */}
      <div className="flex items-center gap-3 pt-1">
        <Button
          variant="outline"
          size="sm"
          onClick={handleSync}
          disabled={syncMutation.isPending}
          className="flex items-center gap-1.5 text-xs h-7"
        >
          {syncMutation.isPending ? (
            <RefreshCw size={11} className="animate-spin" />
          ) : (
            <Save size={11} />
          )}
          {syncMutation.isPending ? "Syncing..." : "Sync to Backend"}
        </Button>

        {syncStatus === "success" && (
          <span className="flex items-center gap-1 text-xs text-profit">
            <CheckCircle2 size={11} />
            Safety config updated
          </span>
        )}
        {syncStatus === "error" && (
          <span className="flex items-center gap-1 text-xs text-warning">
            <AlertTriangle size={11} />
            Backend unreachable — saved locally only
          </span>
        )}
      </div>
    </div>
  );
}
