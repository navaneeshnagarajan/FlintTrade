/**
 * NodePalette.tsx — Left sidebar with categorised, searchable, draggable nodes.
 *
 * Drag a node item onto the React Flow canvas to add it.
 * The drag data-transfer key is "application/flinttrade-node".
 */

import { useState, type DragEvent } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { NODE_CATEGORIES } from "./nodeRegistry";

// ---------------------------------------------------------------------------
// Drag helper
// ---------------------------------------------------------------------------

export const DRAG_MIME = "application/flinttrade-node";

export function setDragNodeType(e: DragEvent<HTMLDivElement>, type: string): void {
  e.dataTransfer.setData(DRAG_MIME, type);
  e.dataTransfer.effectAllowed = "copy";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function NodePalette() {
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["triggers", "actions"]));
  const [search, setSearch] = useState("");

  function toggleCat(id: string): void {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const filtered = search.trim()
    ? NODE_CATEGORIES.map((cat) => ({
        ...cat,
        nodes: cat.nodes.filter(
          (n) =>
            n.label.toLowerCase().includes(search.toLowerCase()) ||
            n.type.toLowerCase().includes(search.toLowerCase())
        ),
      })).filter((cat) => cat.nodes.length > 0)
    : NODE_CATEGORIES;

  return (
    <div
      className="flex flex-col h-full overflow-hidden shrink-0"
      style={{
        width: 188,
        background: "var(--color-base)",
        borderRight: "1px solid var(--color-border)",
      }}
    >
      {/* Header + search */}
      <div style={{ padding: "8px", borderBottom: "1px solid var(--color-border)" }}>
        <div
          style={{
            fontSize: 10,
            fontWeight: 600,
            color: "var(--color-text-muted)",
            marginBottom: 5,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
          }}
        >
          Node Palette
        </div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search nodes…"
          style={{
            width: "100%",
            height: 26,
            fontSize: 11,
            background: "var(--color-card)",
            border: "1px solid var(--color-border)",
            borderRadius: 4,
            color: "var(--color-text)",
            padding: "0 8px",
            outline: "none",
            boxSizing: "border-box",
          }}
        />
      </div>

      {/* Category list */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {filtered.map((cat) => (
          <div key={cat.id}>
            {/* Category header button */}
            <button
              onClick={() => toggleCat(cat.id)}
              style={{
                width: "100%",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "5px 8px",
                background: "var(--color-card)",
                border: "none",
                borderBottom: "1px solid var(--color-border)",
                cursor: "pointer",
                color: cat.color,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <div
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: cat.color,
                    flexShrink: 0,
                  }}
                />
                <span style={{ fontSize: 10, fontWeight: 600 }}>{cat.label}</span>
                <span style={{ fontSize: 9, color: "var(--color-text-muted)" }}>
                  {cat.nodes.length}
                </span>
              </div>
              {expanded.has(cat.id) ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
            </button>

            {/* Node items */}
            {expanded.has(cat.id) && (
              <div style={{ padding: "4px 6px", display: "flex", flexDirection: "column", gap: 2 }}>
                {cat.nodes.map((node) => (
                  <div
                    key={node.type}
                    draggable
                    onDragStart={(e) => setDragNodeType(e, node.type)}
                    title={node.description}
                    style={{
                      padding: "4px 6px",
                      borderRadius: 4,
                      background: "var(--color-card)",
                      border: "1px solid var(--color-border)",
                      cursor: "grab",
                      display: "flex",
                      alignItems: "center",
                      gap: 5,
                      transition: "border-color 0.1s",
                    }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLDivElement).style.borderColor = cat.color;
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLDivElement).style.borderColor = "var(--color-border)";
                    }}
                  >
                    <div
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: "50%",
                        background: cat.color,
                        flexShrink: 0,
                      }}
                    />
                    <span
                      style={{
                        fontSize: 10,
                        color: "var(--color-text)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {node.label}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Drag hint */}
      <div
        style={{
          padding: "6px 8px",
          borderTop: "1px solid var(--color-border)",
          fontSize: 9,
          color: "var(--color-text-muted)",
          textAlign: "center",
        }}
      >
        Drag nodes onto the canvas
      </div>
    </div>
  );
}
