/**
 * SectionHeader.tsx
 *
 * Semantic heading + optional description + optional action button row.
 * Always pairs with a ContentShell section.
 *
 * Usage:
 *   <SectionHeader title="Positions" />
 *
 *   <SectionHeader
 *     title="Holdings"
 *     description="Long-term equity holdings across all accounts"
 *     action={<Button size="sm">Export</Button>}
 *   />
 *
 *   <SectionHeader title="Sub-section" as="h3" />
 */

import * as React from "react";
import { useId } from "react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SectionHeaderProps {
  title: string;
  description?: string;
  /** Optional element (button, link, etc.) rendered flush-right. */
  action?: React.ReactNode;
  /** Semantic heading level. Defaults to "h2". */
  as?: "h2" | "h3" | "h4";
  className?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SectionHeader({
  title,
  description,
  action,
  as: Tag = "h2",
  className,
}: SectionHeaderProps) {
  const headingId = useId();

  return (
    <div
      role="group"
      aria-labelledby={headingId}
      className={cn(
        "flex items-start justify-between gap-4 mb-4",
        className
      )}
    >
      <div>
        <Tag
          id={headingId}
          className="text-lg font-heading font-semibold text-text-primary"
        >
          {title}
        </Tag>
        {description && (
          <p className="mt-1 text-sm text-text-muted">{description}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export default SectionHeader;
