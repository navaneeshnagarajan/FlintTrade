/**
 * ConfigPanel.tsx — Right sidebar shown when a node is selected.
 *
 * Renders dynamic config fields based on node type from NODE_TYPE_TO_FIELDS.
 * Changes are committed immediately to the Zustand store.
 */

import { useState, useEffect } from "react";
import { X, Trash2 } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { NODE_TYPE_TO_FIELDS } from "./nodeRegistry";
import { useFlowStore } from "@/stores/flowStore";
import type { FlowNodeData } from "@/stores/flowStore";

interface ConfigPanelProps {
  nodeId: string;
  data: FlowNodeData;
  onClose: () => void;
}

export function ConfigPanel({ nodeId, data, onClose }: ConfigPanelProps) {
  const updateNodeConfig = useFlowStore((s) => s.updateNodeConfig);
  const updateNodeLabel = useFlowStore((s) => s.updateNodeLabel);
  const removeNode = useFlowStore((s) => s.removeNode);

  const fields = NODE_TYPE_TO_FIELDS.get(data.nodeType) ?? [];
  const [localConfig, setLocalConfig] = useState<Record<string, string>>(data.config ?? {});
  const [localLabel, setLocalLabel] = useState(data.label);

  // Sync when selected node changes
  useEffect(() => {
    setLocalConfig(data.config ?? {});
    setLocalLabel(data.label);
  }, [nodeId, data.config, data.label]);

  function handleFieldChange(key: string, value: string): void {
    const next = { ...localConfig, [key]: value };
    setLocalConfig(next);
    updateNodeConfig(nodeId, next);
  }

  function handleLabelBlur(): void {
    updateNodeLabel(nodeId, localLabel);
  }

  function handleDelete(): void {
    removeNode(nodeId);
    onClose();
  }

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
          {/* Label field */}
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

          {/* Dynamic config fields */}
          {fields.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {fields.map((field) => (
                <div key={field}>
                  <Label
                    style={{
                      fontSize: 10,
                      color: "var(--color-text-muted)",
                      marginBottom: 3,
                      display: "block",
                      textTransform: "capitalize",
                    }}
                  >
                    {field.replace(/([A-Z])/g, " $1").toLowerCase()}
                  </Label>
                  <Input
                    value={localConfig[field] ?? ""}
                    onChange={(e) => handleFieldChange(field, e.target.value)}
                    placeholder={field}
                    style={{
                      height: 28,
                      fontSize: 11,
                      background: "var(--color-base)",
                      border: "1px solid var(--color-border)",
                      color: "var(--color-text)",
                    }}
                  />
                </div>
              ))}
            </div>
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
