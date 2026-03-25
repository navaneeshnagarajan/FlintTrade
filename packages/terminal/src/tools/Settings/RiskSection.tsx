/**
 * RiskSection — MTM stoploss, MTM target, max position lots, max orders per minute.
 */

import { FieldRow, TextInput, SectionTitle } from "./shared";
import { RISK_HINTS } from "@/lib/schemas/riskSchema";

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
    </div>
  );
}
