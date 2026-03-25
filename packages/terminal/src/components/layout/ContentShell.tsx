/**
 * ContentShell.tsx
 *
 * Centered, max-width constrained page wrapper with optional hero slot.
 *
 * Usage:
 *   <ContentShell>
 *     <SectionHeader title="Overview" />
 *     <MyWidget />
 *   </ContentShell>
 *
 *   <ContentShell hero={<PageHero />} maxWidth="4xl">
 *     <SectionHeader title="Narrow Layout" />
 *   </ContentShell>
 */

import * as React from "react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type MaxWidth = "sm" | "md" | "lg" | "xl" | "2xl" | "4xl" | "5xl" | "6xl";

export interface ContentShellProps {
  /** Constrain content width. Defaults to "6xl" (1152px). */
  maxWidth?: MaxWidth;
  /** Optional full-width hero section rendered above the content area. */
  hero?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

// ---------------------------------------------------------------------------
// Max-width class map — avoids Tailwind purging dynamic strings like `max-w-${x}`
// ---------------------------------------------------------------------------

const maxWidthClasses: Record<MaxWidth, string> = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  xl: "max-w-xl",
  "2xl": "max-w-2xl",
  "4xl": "max-w-4xl",
  "5xl": "max-w-5xl",
  "6xl": "max-w-6xl",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ContentShell({
  maxWidth = "6xl",
  hero,
  children,
  className,
}: ContentShellProps) {
  return (
    <div
      className={cn(
        maxWidthClasses[maxWidth],
        "mx-auto",
        "px-4 sm:px-6 lg:px-8 xl:px-12",
        "pt-8 pb-12",
        className
      )}
    >
      {hero && <div className="mb-10">{hero}</div>}
      <div className="space-y-10">{children}</div>
    </div>
  );
}

export default ContentShell;
