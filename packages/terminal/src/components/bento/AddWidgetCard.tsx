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
        border: "1.5px dashed rgba(255,255,255,0.12)",
        borderRadius: "var(--glass-radius-card, 14px)",
        background: "transparent",
        cursor: "pointer",
        transition: "border-color 150ms ease, background 150ms ease",
        outline: "none",
      }}
      whileHover={{ scale: 1.01 }}
      whileTap={{ scale: 0.98 }}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
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
          background: "rgba(255,255,255,0.05)",
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
          color: #22c55e !important;
        }
        .add-widget-card:hover span:last-of-type {
          color: #22c55e !important;
        }
        .add-widget-card:focus-visible {
          outline: 2px solid #22c55e;
          outline-offset: 2px;
        }
      `}</style>
    </motion.button>
  );
}
