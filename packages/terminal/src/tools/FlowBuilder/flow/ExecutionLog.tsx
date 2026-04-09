/**
 * ExecutionLog.tsx — Collapsible execution log panel at the bottom of the editor.
 *
 * Shows timestamped entries with level-coded icons.
 * Cleared via the store's clearLog action.
 */

import { useRef, useEffect } from "react";
import { Terminal, Trash2, ChevronDown, ChevronUp } from "lucide-react";
import { CheckCircle2, XCircle, AlertCircle, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useFlowStore } from "@/stores/flowStore";
import type { LogLevel } from "@/stores/flowStore";

// ---------------------------------------------------------------------------
// Log level icon
// ---------------------------------------------------------------------------

function LevelIcon({ level }: { level: LogLevel }) {
  switch (level) {
    case "success":
      return <CheckCircle2 size={11} className="text-emerald-400 shrink-0" />;
    case "error":
      return <XCircle size={11} className="text-red-400 shrink-0" />;
    case "warning":
      return <AlertCircle size={11} className="text-amber-400 shrink-0" />;
    default:
      return <Info size={11} className="text-sky-400 shrink-0" />;
  }
}

function levelColor(level: LogLevel): string {
  switch (level) {
    case "success": return "text-emerald-300";
    case "error": return "text-red-300";
    case "warning": return "text-amber-300";
    default: return "text-text-secondary";
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ExecutionLogProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function ExecutionLog({ collapsed, onToggle }: ExecutionLogProps) {
  const executionLog = useFlowStore((s) => s.executionLog);
  const clearLog = useFlowStore((s) => s.clearLog);
  const isRunning = useFlowStore((s) => s.isRunning);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Scroll to newest entry when new log arrives and panel is open
  useEffect(() => {
    if (!collapsed && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [executionLog.length, collapsed]);

  return (
    <div
      style={{
        borderTop: "1px solid var(--color-border)",
        background: "var(--color-base)",
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        transition: "height 0.2s",
        height: collapsed ? 32 : 160,
      }}
    >
      {/* Log toolbar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 10px",
          height: 32,
          flexShrink: 0,
          borderBottom: collapsed ? "none" : "1px solid var(--color-border)",
          cursor: "pointer",
        }}
        onClick={onToggle}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Terminal size={11} style={{ color: "var(--color-text-muted)" }} />
          <span style={{ fontSize: 10, fontWeight: 600, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Execution Log
          </span>
          {isRunning && (
            <span style={{ fontSize: 9, color: "#22c55e", animation: "pulse 1.5s infinite" }}>
              RUNNING
            </span>
          )}
          {executionLog.length > 0 && (
            <span
              style={{
                fontSize: 9,
                background: "var(--color-card)",
                border: "1px solid var(--color-border)",
                borderRadius: 8,
                padding: "0 5px",
                color: "var(--color-text-muted)",
              }}
            >
              {executionLog.length}
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }} onClick={(e) => e.stopPropagation()}>
          {!collapsed && executionLog.length > 0 && (
            <Button
              size="sm"
              variant="ghost"
              className="h-5 w-5 p-0 text-text-muted hover:text-red-400"
              onClick={clearLog}
              title="Clear log"
            >
              <Trash2 size={10} />
            </Button>
          )}
          <button
            style={{ color: "var(--color-text-muted)", background: "none", border: "none", cursor: "pointer", padding: 2 }}
            onClick={onToggle}
            aria-label={collapsed ? "Expand log" : "Collapse log"}
          >
            {collapsed ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
        </div>
      </div>

      {/* Log entries */}
      {!collapsed && (
        <div style={{ flex: 1, overflowY: "auto", padding: "4px 10px" }}>
          {executionLog.length === 0 ? (
            <div style={{ fontSize: 10, color: "var(--color-text-muted)", paddingTop: 8 }}>
              No log entries yet. Run the flow to see execution output.
            </div>
          ) : (
            [...executionLog].reverse().map((entry) => (
              <div
                key={entry.id}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 6,
                  padding: "2px 0",
                  borderBottom: "1px solid var(--color-border)",
                }}
              >
                <span style={{ fontSize: 9, color: "var(--color-text-muted)", fontFamily: "monospace", flexShrink: 0, marginTop: 1 }}>
                  {entry.timestamp}
                </span>
                <LevelIcon level={entry.level} />
                <span className={`text-[10px] leading-tight ${levelColor(entry.level)}`}>
                  {entry.message}
                </span>
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}
