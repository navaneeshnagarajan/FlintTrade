/**
 * RiskSection — MTM stoploss, MTM target, max position lots, max orders per minute.
 */

import { FieldRow, TextInput, SectionTitle } from "./shared";

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
        tooltip="Maximum number of lots per single position. Prevents oversizing on any one trade. For example, entering 10 means you cannot hold more than 10 lots of any one instrument at a time. Applies to new orders — existing positions are not auto-closed."
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
        tooltip="Maximum net loss allowed per day in ₹. Trading is blocked when this limit is hit. Reset at market open. Enter a negative rupee amount (e.g. -5000 = stop at ₹5,000 loss). This is a soft limit enforced in the browser only."
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
        tooltip="Mark-to-market (MTM) target: when cumulative unrealised + realised profit for the day reaches this value, a reminder is shown and new orders are blocked. This is a soft limit — use it to lock in daily gains by stopping further trading."
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
        tooltip="Maximum orders per second. SEBI mandates ≤10 OPS for retail algo trading. This cap applies on top of OpenAlgo's own rate limiter. Useful to prevent runaway automation from firing too many orders."
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
