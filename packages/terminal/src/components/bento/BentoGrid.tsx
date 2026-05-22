/**
 * BentoGrid — CSS Grid layout engine for the bento dashboard.
 *
 * Responsive breakpoints:
 *   2400px+  → 6 columns, minmax(260px, 1fr)
 *   1800px+  → auto-fill, minmax(280px, 1fr)
 *   default  → auto-fill, minmax(260px, 1fr)
 *   768px-   → 2 columns
 *   480px-   → 1 column
 */

import React from "react";

interface BentoGridProps {
  children: React.ReactNode;
  className?: string;
  "data-testid"?: string;
}

export function BentoGrid({ children, className = "", "data-testid": testId }: BentoGridProps) {
  return (
    <div
      data-testid={testId}
      className={`bento-grid ${className}`}
      style={{
        display: "grid",
        gap: "8px",
        alignItems: "start",
      }}
    >
      {children}
      <style>{`
        .bento-grid {
          grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
        }
        @media (min-width: 1800px) {
          .bento-grid {
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
          }
        }
        @media (min-width: 2400px) {
          .bento-grid {
            grid-template-columns: repeat(6, 1fr);
          }
        }
        @media (max-width: 768px) {
          .bento-grid {
            grid-template-columns: repeat(2, 1fr);
          }
        }
        @media (max-width: 480px) {
          .bento-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
}

/**
 * BentoGridContainer — scrollable wrapper for the BentoGrid with thin scrollbar.
 */
export function BentoGridContainer({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={`bento-scroll-container ${className}`}
      style={{
        overflowY: "auto",
        overflowX: "hidden",
        height: "100%",
        scrollbarWidth: "thin",
        scrollbarColor: "var(--color-border-default) transparent",
      }}
    >
      {children}
      <style>{`
        .bento-scroll-container::-webkit-scrollbar {
          width: 4px;
        }
        .bento-scroll-container::-webkit-scrollbar-track {
          background: transparent;
        }
        .bento-scroll-container::-webkit-scrollbar-thumb {
          background: var(--color-border-default);
          border-radius: 2px;
        }
        .bento-scroll-container::-webkit-scrollbar-thumb:hover {
          background: var(--color-border-strong);
        }
      `}</style>
    </div>
  );
}
