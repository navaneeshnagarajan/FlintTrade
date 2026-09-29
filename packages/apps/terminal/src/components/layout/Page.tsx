/**
 * Page.tsx — the shared frame every app route is built from.
 *
 *   <Page>
 *     <PageHeader title="Invest" description="…" actions={…}>
 *       <PageTabs … />
 *     </PageHeader>
 *     <PageBody width="default">…</PageBody>
 *   </Page>
 *
 * PageHeader owns the route's single visible H1 and uses the same padding,
 * type scale and divider on every page. PageBody is the scroll container:
 * one gutter, one set of widths, and bottom room so the last row is never
 * hidden behind floating chrome.
 */

import * as React from "react";
import { useCallback, useRef } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export type PageProps = React.HTMLAttributes<HTMLDivElement>;

export function Page({ className, children, ...rest }: PageProps) {
  return (
    <div
      className={cn("flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-surface-base", className)}
      {...rest}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PageHeader
// ---------------------------------------------------------------------------

export interface PageHeaderProps {
  /** The route's H1. Must match the route's navigation label. */
  title: React.ReactNode;
  /** One line that says what the page is for. */
  description?: React.ReactNode;
  /** Right-aligned page actions (buttons, menus, toggles). */
  actions?: React.ReactNode;
  /** Small status chips rendered beside the title. */
  meta?: React.ReactNode;
  /** Secondary navigation, usually PageTabs, rendered under the title row. */
  children?: React.ReactNode;
  className?: string;
  /** Anchor for SpotlightTour steps. */
  tourTarget?: string;
  "data-testid"?: string;
}

export function PageHeader({
  title,
  description,
  actions,
  meta,
  children,
  className,
  tourTarget,
  "data-testid": testId = "page-header",
}: PageHeaderProps) {
  return (
    <header
      data-testid={testId}
      data-tour-target={tourTarget}
      className={cn(
        "shrink-0 border-b border-border-default bg-surface-base px-[var(--ft-page-gutter)]",
        children ? "pt-5" : "py-5",
        className,
      )}
    >
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            <h1 className="ft-text-page-title break-words text-text-primary">{title}</h1>
            {meta ? <div className="flex flex-wrap items-center gap-2">{meta}</div> : null}
          </div>
          {description ? (
            <p className="ft-text-body mt-1 max-w-3xl text-text-secondary">{description}</p>
          ) : null}
        </div>
        {actions ? (
          <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
        ) : null}
      </div>
      {children ? <div className="-mb-px mt-4 min-w-0">{children}</div> : null}
    </header>
  );
}

// ---------------------------------------------------------------------------
// PageTabs
// ---------------------------------------------------------------------------

export interface PageTab<T extends string> {
  id: T;
  label: string;
  icon?: LucideIcon;
  /** Trailing count or status chip. */
  badge?: React.ReactNode;
}

export interface PageTabsProps<T extends string> {
  tabs: readonly PageTab<T>[];
  value: T;
  onChange: (id: T) => void;
  /** Accessible name of the tablist, e.g. "Invest sections". */
  label: string;
  /** Tab ids are `${idPrefix}-tab-${id}`, panel ids `${idPrefix}-tabpanel-${id}`. */
  idPrefix: string;
  className?: string;
}

export function pageTabId(idPrefix: string, id: string): string {
  return `${idPrefix}-tab-${id}`;
}

export function pageTabPanelId(idPrefix: string, id: string): string {
  return `${idPrefix}-tabpanel-${id}`;
}

/**
 * Horizontal ARIA tablist with a roving tab stop: Left/Right move and
 * activate, Home/End jump to the ends. Scrolls sideways when it cannot fit.
 */
export function PageTabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
  idPrefix,
  className,
}: PageTabsProps<T>) {
  const listRef = useRef<HTMLDivElement>(null);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const buttons = listRef.current?.querySelectorAll<HTMLButtonElement>("[role='tab']");
      if (!buttons || buttons.length === 0) return;
      const current = Array.from(buttons).indexOf(document.activeElement as HTMLButtonElement);
      const from = current >= 0 ? current : tabs.findIndex((tab) => tab.id === value);
      let next = from;
      if (event.key === "ArrowRight") next = (from + 1) % buttons.length;
      else if (event.key === "ArrowLeft") next = (from - 1 + buttons.length) % buttons.length;
      else if (event.key === "Home") next = 0;
      else next = buttons.length - 1;
      buttons[next]?.focus();
      const nextTab = tabs[next];
      if (nextTab) onChange(nextTab.id);
    },
    [onChange, tabs, value],
  );

  return (
    <div
      ref={listRef}
      role="tablist"
      aria-label={label}
      aria-orientation="horizontal"
      onKeyDown={handleKeyDown}
      className={cn(
        "flex min-w-0 items-end gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        className,
      )}
    >
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const active = tab.id === value;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={pageTabId(idPrefix, tab.id)}
            aria-selected={active}
            aria-controls={pageTabPanelId(idPrefix, tab.id)}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(tab.id)}
            className={cn(
              "flex h-10 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-t-md border-b-2 px-3 text-sm font-medium transition-colors",
              "focus-visible:outline-offset-[-2px]",
              active
                ? "border-accent text-text-primary"
                : "border-transparent text-text-secondary hover:border-border-strong hover:text-text-primary",
            )}
          >
            {Icon ? <Icon className="size-4 shrink-0" aria-hidden="true" /> : null}
            {tab.label}
            {tab.badge}
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PageBody
// ---------------------------------------------------------------------------

export type PageWidth = "narrow" | "default" | "wide" | "full";

const WIDTH_CLASS: Record<PageWidth, string> = {
  narrow: "max-w-[var(--ft-page-width-narrow)]",
  default: "max-w-[var(--ft-page-width)]",
  wide: "max-w-[var(--ft-page-width-wide)]",
  full: "max-w-none",
};

export interface PageBodyProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Content width: narrow 768 px, default 1152 px, wide 1440 px, or full. */
  width?: PageWidth;
  /** Apply the page gutter and vertical rhythm. Off for edge-to-edge tools. */
  padded?: boolean;
  /** Classes for the width-constrained inner column. */
  innerClassName?: string;
}

export function PageBody({
  width = "default",
  padded = true,
  className,
  innerClassName,
  children,
  ...rest
}: PageBodyProps) {
  return (
    <div className={cn("min-h-0 min-w-0 flex-1 overflow-y-auto", className)} {...rest}>
      <div
        className={cn(
          "mx-auto w-full min-w-0",
          WIDTH_CLASS[width],
          padded && "px-[var(--ft-page-gutter)] pb-16 pt-6",
          innerClassName,
        )}
      >
        {children}
      </div>
    </div>
  );
}
