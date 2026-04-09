/**
 * ConfigPanel.tsx — Right sidebar shown when a node is selected.
 *
 * Renders config fields declaratively from NodeTypeDescriptor metadata.
 * Falls back to plain Input fields for nodes without full descriptors.
 *
 * Field type → widget mapping:
 *   string     → Input
 *   number     → Input type="number" with min/max
 *   boolean    → Switch
 *   select     → Select with options
 *   expression → ExpressionInput ({{...}} highlighting + autocomplete)
 *   symbol     → Input with "SYM" badge (symbol search placeholder)
 *   exchange   → Select (NSE / BSE / NFO / BFO / MCX / CDS)
 */

import { useState, useEffect, useCallback } from "react";
import { X, Trash2, HelpCircle } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { NODE_TYPE_TO_FIELDS, NODE_DESCRIPTORS } from "./nodeRegistry";
import type { NodeFieldDescriptor } from "./nodeRegistry";
import { ExpressionInput } from "./ExpressionInput";
import { useFlowStore } from "@/stores/flowStore";
import type { FlowNodeData } from "@/stores/flowStore";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const EXCHANGE_OPTIONS: { label: string; value: string }[] = [
  { label: "NSE (Equity)", value: "NSE" },
  { label: "BSE (Equity)", value: "BSE" },
  { label: "NFO (F&O)", value: "NFO" },
  { label: "BFO (BSE F&O)", value: "BFO" },
  { label: "MCX (Commodity)", value: "MCX" },
  { label: "CDS (Currency)", value: "CDS" },
  { label: "NSE_INDEX", value: "NSE_INDEX" },
  { label: "BSE_INDEX", value: "BSE_INDEX" },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ConfigPanelProps {
  nodeId: string;
  data: FlowNodeData;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Sub-components for each field type
// ---------------------------------------------------------------------------

interface FieldProps {
  field: NodeFieldDescriptor;
  value: string;
  onChange: (value: string) => void;
}

function StringField({ field, value, onChange }: FieldProps) {
  return (
    <Input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={field.placeholder ?? field.key}
      required={field.required}
      style={{
        height: 28,
        fontSize: 11,
        background: "var(--color-base)",
        border: "1px solid var(--color-border)",
        color: "var(--color-text)",
      }}
    />
  );
}

function NumberField({ field, value, onChange }: FieldProps) {
  const min = field.validation?.min;
  const max = field.validation?.max;
  return (
    <Input
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={field.placeholder ?? String(field.default ?? "")}
      min={min}
      max={max}
      required={field.required}
      style={{
        height: 28,
        fontSize: 11,
        background: "var(--color-base)",
        border: "1px solid var(--color-border)",
        color: "var(--color-text)",
      }}
    />
  );
}

function BooleanField({ field, value, onChange }: FieldProps) {
  const checked = value === "true";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <Switch
        id={`switch-${field.key}`}
        checked={checked}
        onCheckedChange={(v) => onChange(String(v))}
        aria-label={field.label}
      />
      <span style={{ fontSize: 10, color: "var(--color-text-muted)" }}>
        {checked ? "Enabled" : "Disabled"}
      </span>
    </div>
  );
}

function SelectField({ field, value, onChange }: FieldProps) {
  const options = field.options ?? [];
  return (
    <Select value={value || String(field.default ?? "")} onValueChange={onChange}>
      <SelectTrigger
        style={{
          height: 28,
          fontSize: 11,
          background: "var(--color-base)",
          border: "1px solid var(--color-border)",
          color: "var(--color-text)",
        }}
      >
        <SelectValue placeholder={field.placeholder ?? `Select ${field.label}`} />
      </SelectTrigger>
      <SelectContent>
        {options.map((opt) => (
          <SelectItem key={opt.value} value={opt.value} style={{ fontSize: 11 }}>
            {opt.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function ExchangeField({ field, value, onChange }: FieldProps) {
  return (
    <Select value={value || String(field.default ?? "NSE")} onValueChange={onChange}>
      <SelectTrigger
        style={{
          height: 28,
          fontSize: 11,
          background: "var(--color-base)",
          border: "1px solid var(--color-border)",
          color: "var(--color-text)",
        }}
      >
        <SelectValue placeholder="Select exchange" />
      </SelectTrigger>
      <SelectContent>
        {EXCHANGE_OPTIONS.map((opt) => (
          <SelectItem key={opt.value} value={opt.value} style={{ fontSize: 11 }}>
            {opt.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function SymbolField({ field, value, onChange }: FieldProps) {
  return (
    <div style={{ position: "relative" }}>
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value.toUpperCase())}
        placeholder={field.placeholder ?? "e.g. NIFTY"}
        required={field.required}
        style={{
          height: 28,
          fontSize: 11,
          background: "var(--color-base)",
          border: "1px solid var(--color-border)",
          color: "var(--color-text)",
          paddingRight: 36,
        }}
      />
      <span
        aria-hidden="true"
        style={{
          position: "absolute",
          right: 6,
          top: "50%",
          transform: "translateY(-50%)",
          fontSize: 8,
          fontWeight: 700,
          color: "#38bdf8",
          letterSpacing: "0.05em",
          pointerEvents: "none",
        }}
      >
        SYM
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Field renderer — dispatches to the correct sub-component
// ---------------------------------------------------------------------------

function renderField(
  field: NodeFieldDescriptor,
  value: string,
  onChange: (v: string) => void
): React.ReactNode {
  switch (field.type) {
    case "number":
      return <NumberField field={field} value={value} onChange={onChange} />;
    case "boolean":
      return <BooleanField field={field} value={value} onChange={onChange} />;
    case "select":
      return <SelectField field={field} value={value} onChange={onChange} />;
    case "exchange":
      return <ExchangeField field={field} value={value} onChange={onChange} />;
    case "symbol":
      return <SymbolField field={field} value={value} onChange={onChange} />;
    case "expression":
      return (
        <ExpressionInput
          label=""
          value={value}
          onChange={onChange}
          placeholder={field.placeholder}
          helpText={undefined}
          required={field.required}
        />
      );
    default:
      return <StringField field={field} value={value} onChange={onChange} />;
  }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ConfigPanel({ nodeId, data, onClose }: ConfigPanelProps) {
  const updateNodeConfig = useFlowStore((s) => s.updateNodeConfig);
  const updateNodeLabel = useFlowStore((s) => s.updateNodeLabel);
  const removeNode = useFlowStore((s) => s.removeNode);

  // Prefer descriptor fields; fall back to legacy string[] fields
  const descriptor = NODE_DESCRIPTORS.get(data.nodeType);
  const legacyFields = NODE_TYPE_TO_FIELDS.get(data.nodeType) ?? [];

  const [localConfig, setLocalConfig] = useState<Record<string, string>>(data.config ?? {});
  const [localLabel, setLocalLabel] = useState(data.label);

  // Sync when selected node changes
  useEffect(() => {
    setLocalConfig(data.config ?? {});
    setLocalLabel(data.label);
  }, [nodeId, data.config, data.label]);

  const handleFieldChange = useCallback(
    (key: string, value: string) => {
      const next = { ...localConfig, [key]: value };
      setLocalConfig(next);
      updateNodeConfig(nodeId, next);
    },
    [localConfig, nodeId, updateNodeConfig]
  );

  function handleLabelBlur(): void {
    updateNodeLabel(nodeId, localLabel);
  }

  function handleDelete(): void {
    removeNode(nodeId);
    onClose();
  }

  // ---------------------------------------------------------------------------
  // Field rendering helpers
  // ---------------------------------------------------------------------------

  function renderDescriptorField(field: NodeFieldDescriptor): React.ReactNode {
    const currentValue = localConfig[field.key] ?? String(field.default ?? "");

    return (
      <div key={field.key} style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {/* Skip duplicate label for expression type — ExpressionInput has its own */}
        {field.type !== "expression" && (
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <Label
              style={{
                fontSize: 10,
                color: "var(--color-text-muted)",
                display: "block",
              }}
            >
              {field.label}
              {field.required && (
                <span style={{ color: "#f87171", marginLeft: 2 }} aria-hidden="true">
                  *
                </span>
              )}
            </Label>
            {field.helpText && (
              <span
                title={field.helpText}
                aria-label={field.helpText}
                style={{ color: "var(--color-text-muted)", cursor: "help", lineHeight: 1 }}
              >
                <HelpCircle size={9} />
              </span>
            )}
          </div>
        )}

        {field.type === "expression" ? (
          <ExpressionInput
            label={field.label}
            value={currentValue}
            onChange={(v) => handleFieldChange(field.key, v)}
            placeholder={field.placeholder}
            helpText={field.helpText}
            required={field.required}
          />
        ) : (
          renderField(field, currentValue, (v) => handleFieldChange(field.key, v))
        )}
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div
      style={{
        width: 220,
        flexShrink: 0,
        background: "var(--color-card)",
        borderLeft: "1px solid var(--color-border)",
        display: "flex",
        flexDirection: "column",
        height: "100%",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 10px",
          borderBottom: "1px solid var(--color-border)",
        }}
      >
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text)" }}>
            Node Config
          </div>
          <div
            style={{
              fontSize: 9,
              color: "var(--color-text-muted)",
              fontFamily: "var(--font-mono, monospace)",
            }}
          >
            {data.nodeType}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            color: "var(--color-text-muted)",
            cursor: "pointer",
            background: "none",
            border: "none",
            padding: 2,
          }}
          aria-label="Close config panel"
        >
          <X size={13} />
        </button>
      </div>

      <ScrollArea style={{ flex: 1 }}>
        <div style={{ padding: "10px" }}>
          {/* Node label */}
          <div style={{ marginBottom: 10 }}>
            <Label
              style={{
                fontSize: 10,
                color: "var(--color-text-muted)",
                marginBottom: 4,
                display: "block",
              }}
            >
              Label
            </Label>
            <Input
              value={localLabel}
              onChange={(e) => setLocalLabel(e.target.value)}
              onBlur={handleLabelBlur}
              style={{
                height: 28,
                fontSize: 11,
                background: "var(--color-base)",
                border: "1px solid var(--color-border)",
                color: "var(--color-text)",
              }}
            />
          </div>

          {/* Category badge */}
          <div style={{ marginBottom: 10 }}>
            <div
              style={{
                fontSize: 9,
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                padding: "2px 6px",
                borderRadius: 4,
                background: `${data.color}22`,
                color: data.color,
                border: `1px solid ${data.color}44`,
              }}
            >
              {data.category}
            </div>
          </div>

          {/* Descriptor hint badge */}
          {descriptor && (
            <div
              style={{
                fontSize: 9,
                color: "var(--color-text-muted)",
                marginBottom: 8,
                display: "flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              <span
                style={{
                  display: "inline-block",
                  width: 5,
                  height: 5,
                  borderRadius: "50%",
                  background: "#22c55e",
                }}
              />
              {descriptor.description}
            </div>
          )}

          {/* Config fields */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {descriptor && descriptor.fields.length > 0 ? (
              // Metadata-driven rendering
              descriptor.fields.map((field) => renderDescriptorField(field))
            ) : legacyFields.length > 0 ? (
              // Legacy fallback — plain Input for each field key
              legacyFields.map((fieldKey) => (
                <div key={fieldKey}>
                  <Label
                    style={{
                      fontSize: 10,
                      color: "var(--color-text-muted)",
                      marginBottom: 3,
                      display: "block",
                      textTransform: "capitalize",
                    }}
                  >
                    {fieldKey.replace(/([A-Z])/g, " $1").toLowerCase()}
                  </Label>
                  <Input
                    value={localConfig[fieldKey] ?? ""}
                    onChange={(e) => handleFieldChange(fieldKey, e.target.value)}
                    placeholder={fieldKey}
                    style={{
                      height: 28,
                      fontSize: 11,
                      background: "var(--color-base)",
                      border: "1px solid var(--color-border)",
                      color: "var(--color-text)",
                    }}
                  />
                </div>
              ))
            ) : (
              <div
                style={{
                  fontSize: 11,
                  color: "var(--color-text-muted)",
                  padding: "8px 0",
                }}
              >
                No configuration fields for this node type.
              </div>
            )}
          </div>

          {/* Delete node */}
          <div style={{ marginTop: 16 }}>
            <Button
              size="sm"
              variant="ghost"
              className="w-full h-7 text-red-400 hover:text-red-300 hover:bg-red-950 text-xs gap-1.5 justify-start"
              onClick={handleDelete}
            >
              <Trash2 size={11} />
              Delete node
            </Button>
          </div>
        </div>
      </ScrollArea>
    </div>
  );
}
