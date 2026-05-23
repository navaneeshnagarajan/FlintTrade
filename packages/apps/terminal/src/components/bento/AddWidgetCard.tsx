/**
 * AddWidgetCard — Dashed border card at the end of the bento grid.
 * Clicking opens the widget picker.
 */

import { motion } from "framer-motion";
import { Plus } from "lucide-react";

interface AddWidgetCardProps {
  onClick?: () => void;
}

export function AddWidgetCard({ onClick }: AddWidgetCardProps) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      data-testid="add-widget-card"
      aria-label="Add widget"
      className="add-widget-card"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "8px",
        minHeight: "120px",
        width: "100%",
        border: "1.5px dashed var(--color-border-default)",
        borderRadius: "var(--glass-radius-card, 14px)",
        background: "transparent",
        cursor: "pointer",
        transition: "border-color 150ms ease, background 150ms ease",
        outline: "none",
      }}
      whileHover={{ scale: 1.01 }}
      whileTap={{ scale: 0.98 }}
    >
      <span
        className="add-widget-icon"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: "32px",
          height: "32px",
          borderRadius: "50%",
          background: "var(--glass-l2-bg, var(--color-surface-elevated))",
          transition: "background 150ms ease",
        }}
      >
        <Plus size={16} strokeWidth={2} aria-hidden="true" />
      </span>
      <span
        style={{
          fontSize: "11px",
          fontWeight: 500,
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          color: "var(--color-text-muted, #505068)",
          transition: "color 150ms ease",
        }}
      >
        Add Widget
      </span>
      <style>{`
        .add-widget-card:hover {
          border-color: rgba(34, 197, 94, 0.5) !important;
          background: rgba(34, 197, 94, 0.04) !important;
        }
        .add-widget-card:hover .add-widget-icon {
          background: rgba(34, 197, 94, 0.1) !important;
          color: var(--color-accent) !important;
        }
        .add-widget-card:hover span:last-of-type {
          color: var(--color-accent) !important;
        }
        .add-widget-card:focus-visible {
          outline: 2px solid var(--color-accent);
          outline-offset: 2px;
        }
      `}</style>
    </motion.button>
  );
}
