/**
 * BentoCard — Glass surface card for the bento dashboard.
 *
 * Size variants:
 *   default  → 1×1 (standard)
 *   wide     → 2×1 (grid-column: span 2)
 *   tall     → 1×2 (grid-row: span 2)
 *   hero     → 2×2 (grid-column: span 2, grid-row: span 2)
 */

import { motion } from "framer-motion";
import React from "react";

export type BentoCardSize = "default" | "wide" | "tall" | "hero";

const sizeStyles: Record<BentoCardSize, React.CSSProperties> = {
  default: {},
  wide: { gridColumn: "span 2" },
  tall: { gridRow: "span 2" },
  hero: { gridColumn: "span 2", gridRow: "span 2" },
};

interface BentoCardProps {
  size?: BentoCardSize;
  children: React.ReactNode;
  className?: string;
  /** Optional accessible label for the card region */
  label?: string;
  /** Data attribute for test targeting */
  "data-testid"?: string;
}

export function BentoCard({
  size = "default",
  children,
  className = "",
  label,
  "data-testid": testId,
}: BentoCardProps) {
  return (
    <motion.div
      data-testid={testId}
      data-bento-size={size}
      aria-label={label}
      style={{
        ...sizeStyles[size],
        background: "var(--glass-l1-bg, rgba(255,255,255,0.018))",
        border: "1px solid var(--glass-l1-border, rgba(255,255,255,0.045))",
        borderRadius: "var(--glass-radius-card, 14px)",
        backdropFilter: "var(--glass-blur, blur(16px))",
        overflow: "hidden",
        position: "relative",
      }}
      className={`bento-card ${className}`}
      whileHover={{
        y: -1,
        transition: { duration: 0.15, ease: "easeOut" },
      }}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
    >
      {/* Inset top highlight on hover — rendered via CSS */}
      <div className="bento-card-inset" aria-hidden="true" />
      {children}
      <style>{`
        .bento-card {
          transition: border-color 150ms ease, box-shadow 150ms ease;
        }
        .bento-card:hover {
          border-color: var(--glass-hover-border, rgba(255,255,255,0.09));
          box-shadow: var(--glass-hover-shadow, 0 8px 32px rgba(0,0,0,0.3)),
                      var(--glass-hover-inset, inset 0 1px 0 rgba(255,255,255,0.04));
        }
        .bento-card-inset {
          position: absolute;
          inset: 0;
          border-radius: inherit;
          pointer-events: none;
        }
        .bento-card:hover .bento-card-inset {
          box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);
        }
      `}</style>
    </motion.div>
  );
}
