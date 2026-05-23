/**
 * PriceAlertNode.tsx — Canvas node for the Price Alert trigger.
 *
 * Rendered directly on the React Flow canvas as a custom node type.
 * Displays: symbol badge, condition label, price/channel/percent value,
 * and cooldown.  All editing still happens in ConfigPanel (right sidebar).
 *
 * 10 condition types (see nodeRegistry.ts):
 *   Crossing Up · Crossing Down · Entering Channel · Exiting Channel
 *   Moving Up % · Moving Down % · Greater Than · Less Than
 *   Inside Channel · Outside Channel
 */

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { BellRing } from "lucide-react";
import {
  CATEGORY_COLORS,
  PRICE_ALERT_CONDITIONS,
  CHANNEL_CONDITIONS,
  PERCENT_CONDITIONS,
} from "../nodeRegistry";
import type { PriceAlertCondition } from "../nodeRegistry";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function conditionLabel(value: string): string {
  return (
    PRICE_ALERT_CONDITIONS.find((c) => c.value === value)?.label ?? value
  );
}

function formatValue(
  condition: PriceAlertCondition,
  price: string,
  priceUpper: string,
  pctValue: string
): string {
  if (PERCENT_CONDITIONS.has(condition)) {
    return pctValue ? `${pctValue}%` : "—";
  }
  if (CHANNEL_CONDITIONS.has(condition)) {
    const lo = price || "—";
    const hi = priceUpper || "—";
    return `${lo} – ${hi}`;
  }
  return price || "—";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface PriceAlertNodeData {
  label: string;
  nodeType: string;
  color: string;
  config: Record<string, string>;
  selected?: boolean;
}

interface PriceAlertNodeProps {
  data: PriceAlertNodeData;
  selected?: boolean;
}

export const PriceAlertNode = memo(function PriceAlertNode({
  data,
  selected,
}: PriceAlertNodeProps) {
  const amber = CATEGORY_COLORS.triggers;
  const config = data.config ?? {};

  const symbol: string = config["symbol"] ?? "";
  const exchange: string = config["exchange"] ?? "NSE";
  const condition = (config["condition"] ?? "crossingUp") as PriceAlertCondition;
  const price: string = config["price"] ?? "";
  const priceUpper: string = config["priceUpper"] ?? "";
  const pctValue: string = config["pctValue"] ?? "";
  const cooldown: string = config["cooldownSecs"] ?? "60";

  const valueDisplay = formatValue(condition, price, priceUpper, pctValue);

  return (
    <div
      role="group"
      aria-label={`Price Alert node: ${data.label}`}
      style={{
        minWidth: 168,
        background: "var(--color-card, #16161f)",
        border: `1.5px solid ${selected ? amber : "var(--color-border, #2a2a3a)"}`,
        borderRadius: 7,
        boxShadow: selected ? `0 0 0 2px ${amber}44` : "none",
        fontFamily: "inherit",
        overflow: "hidden",
        transition: "border-color 0.15s, box-shadow 0.15s",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "5px 8px",
          background: `${amber}18`,
          borderBottom: `1px solid ${amber}33`,
        }}
      >
        <BellRing size={12} color={amber} aria-hidden="true" />
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: amber,
            letterSpacing: "0.03em",
            textTransform: "uppercase",
          }}
        >
          Price Alert
        </span>
      </div>

      {/* Body */}
      <div style={{ padding: "6px 8px", display: "flex", flexDirection: "column", gap: 4 }}>
        {/* Symbol + exchange */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 4 }}>
          <span
            style={{
              fontSize: 12,
              fontWeight: 700,
              color: "var(--color-text, #e2e2e8)",
              fontFamily: "var(--font-mono, monospace)",
            }}
          >
            {symbol || <em style={{ color: "var(--color-text-muted, #6b7280)", fontStyle: "normal" }}>SYMBOL</em>}
          </span>
          <span
            style={{
              fontSize: 8,
              fontWeight: 600,
              padding: "1px 4px",
              borderRadius: 3,
              background: "var(--color-base, #0a0a0f)",
              border: "1px solid var(--color-border, #2a2a3a)",
              color: "var(--color-text-muted, #6b7280)",
              letterSpacing: "0.04em",
            }}
          >
            {exchange}
          </span>
        </div>

        {/* Condition */}
        <div
          style={{
            fontSize: 10,
            color: "var(--color-text-secondary, #a0a0b8)",
            background: "var(--color-base, #0a0a0f)",
            borderRadius: 4,
            padding: "2px 5px",
            display: "inline-flex",
            alignItems: "center",
            gap: 3,
          }}
        >
          <span style={{ color: amber }}>if</span>
          {conditionLabel(condition)}
        </div>

        {/* Value row */}
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: "var(--color-text, #e2e2e8)",
            fontFamily: "var(--font-mono, monospace)",
          }}
        >
          {valueDisplay}
        </div>

        {/* Cooldown */}
        {Number(cooldown) > 0 && (
          <div
            style={{
              fontSize: 9,
              color: "var(--color-text-muted, #6b7280)",
              marginTop: 1,
            }}
          >
            Cooldown: {cooldown}s
          </div>
        )}
      </div>

      {/* Custom label (if not default) */}
      {data.label && data.label !== "Price Alert" && (
        <div
          style={{
            fontSize: 9,
            color: "var(--color-text-muted, #6b7280)",
            borderTop: "1px solid var(--color-border, #2a2a3a)",
            padding: "3px 8px",
            fontStyle: "italic",
          }}
        >
          {data.label}
        </div>
      )}

      {/* Output handle — triggers have no input handle */}
      <Handle
        type="source"
        position={Position.Right}
        id="out"
        style={{
          background: amber,
          border: "2px solid var(--color-card, #16161f)",
          width: 10,
          height: 10,
        }}
        aria-label="Trigger output"
      />
    </div>
  );
});
