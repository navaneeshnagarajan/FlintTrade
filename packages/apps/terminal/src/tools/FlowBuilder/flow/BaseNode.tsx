/**
 * BaseNode.tsx — React Flow custom node component.
 *
 * Renders all flow builder node types with:
 * - Colour-coded left border + header tint by category
 * - Top input handle (hidden for start nodes)
 * - Bottom output handle(s) — single or conditional (true/false)
 * - Config field preview (up to 2 key-value pairs)
 * - Selection ring
 */

import { memo } from "react";
import { Handle, Position, useStore } from "@xyflow/react";
import { CONDITIONAL_NODE_TYPES, START_NODE_TYPES } from "./nodeRegistry";
import { PriceAlertNode } from "./nodes/PriceAlertNode";
import type { FlowNodeData } from "@/stores/flowStore";
import type { NodeProps, Node } from "@xyflow/react";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function BaseNodeInner({ id, data, selected }: NodeProps<Node<FlowNodeData>>) {
  const { label, nodeType, color, config } = data;
  const isConditional = CONDITIONAL_NODE_TYPES.has(nodeType);
  const isStart = START_NODE_TYPES.has(nodeType);
  const configEntries = Object.entries(config ?? {}).slice(0, 2);

  // Track whether this node is being connected so we can highlight handles
  const isConnecting = useStore((s) => s.connection.inProgress);

  return (
    <div
      style={{
        minWidth: 160,
        maxWidth: 180,
        background: "var(--color-card)",
        border: `1px solid ${selected ? color : "var(--color-border)"}`,
        borderLeft: `3px solid ${color}`,
        borderRadius: 6,
        boxShadow: selected ? `0 0 0 2px ${color}40, 0 4px 12px rgba(0,0,0,0.4)` : "0 2px 6px rgba(0,0,0,0.3)",
        overflow: "visible",
        userSelect: "none",
        transition: "border-color 0.15s, box-shadow 0.15s",
      }}
    >
      {/* Input handle — top centre (hidden for start nodes) */}
      {!isStart && (
        <Handle
          type="target"
          position={Position.Top}
          style={{
            background: isConnecting ? color : "#6b6b8a",
            border: "2px solid var(--color-base)",
            width: 10,
            height: 10,
            top: -5,
          }}
        />
      )}

      {/* Header */}
      <div
        style={{
          padding: "5px 8px",
          background: `${color}18`,
          borderBottom: configEntries.length > 0 ? "1px solid var(--color-border)" : undefined,
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        {/* Category dot */}
        <div
          style={{
            width: 7,
            height: 7,
            borderRadius: "50%",
            background: color,
            flexShrink: 0,
          }}
        />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: "var(--color-text)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              lineHeight: 1.3,
            }}
          >
            {label}
          </div>
          <div
            style={{
              fontSize: 9,
              color: "var(--color-text-muted)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              fontFamily: "var(--font-mono, monospace)",
            }}
          >
            {nodeType}
          </div>
        </div>
      </div>

      {/* Config preview */}
      {configEntries.length > 0 && (
        <div style={{ padding: "4px 8px 6px", display: "flex", flexDirection: "column", gap: 2 }}>
          {configEntries.map(([k, v]) => (
            <div
              key={k}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                background: "var(--color-base)",
                borderRadius: 3,
                padding: "2px 5px",
              }}
            >
              <span style={{ fontSize: 9, color: "var(--color-text-muted)" }}>{k}</span>
              <span
                style={{
                  fontSize: 9,
                  color: "var(--color-text)",
                  fontFamily: "var(--font-mono, monospace)",
                  maxWidth: 70,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {String(v)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Output handles — bottom */}
      {isConditional ? (
        <>
          {/* True output */}
          <Handle
            id="true"
            type="source"
            position={Position.Bottom}
            style={{
              background: "#22c55e",
              border: "2px solid var(--color-base)",
              width: 10,
              height: 10,
              bottom: -5,
              left: "30%",
            }}
          />
          {/* False output */}
          <Handle
            id="false"
            type="source"
            position={Position.Bottom}
            style={{
              background: "#f87171",
              border: "2px solid var(--color-base)",
              width: 10,
              height: 10,
              bottom: -5,
              left: "70%",
            }}
          />
          {/* Labels for true/false */}
          <div
            style={{
              position: "absolute",
              bottom: -18,
              left: 0,
              right: 0,
              display: "flex",
              justifyContent: "space-around",
              pointerEvents: "none",
            }}
          >
            <span style={{ fontSize: 8, color: "#22c55e", marginLeft: -4 }}>T</span>
            <span style={{ fontSize: 8, color: "#f87171", marginRight: -4 }}>F</span>
          </div>
        </>
      ) : (
        <Handle
          id={`${id}-output`}
          type="source"
          position={Position.Bottom}
          style={{
            background: "#6c8ef0",
            border: "2px solid var(--color-base)",
            width: 10,
            height: 10,
            bottom: -5,
          }}
        />
      )}
    </div>
  );
}

export const BaseNode = memo(BaseNodeInner);
BaseNode.displayName = "BaseNode";

// React Flow nodeTypes map — imported in the canvas
export const REACT_FLOW_NODE_TYPES = {
  flowNode: BaseNode,
  priceAlertNode: PriceAlertNode,
} as const;
