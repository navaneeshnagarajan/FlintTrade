/**
 * SectionNav.tsx — labelled section navigation for pages with many sections
 * (Settings, Learn, Automate).
 *
 * A vertical column with optional group headings from 768 px up, and a
 * horizontally scrolling row below that. Labels are always visible; an
 * optional `collapsed` mode shows icons only, with the label as tooltip.
 *
 * Semantics are an ARIA tablist with a roving tab stop. Only the selected tab
 * points at a panel, because only that panel is mounted.
 */

import * as React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export const SECTION_NAV_DESKTOP_QUERY = "(min-width: 768px)";

export interface SectionNavItem<T extends string> {
  id: T;
  label: string;
  icon?: LucideIcon;
  /** Trailing status (a dot or count). */
  indicator?: React.ReactNode;
  /** Optional completion percentage (0–100); renders a bar under the tab when expanded. */
  progress?: number;
  /** Extra hover text; defaults to the label. */
  title?: string;
}

export interface SectionNavGroup<T extends string> {
  id: string;
  /** Visible heading above the group (vertical layout only). */
  label?: string;
  items: readonly SectionNavItem<T>[];
}

export interface SectionNavProps<T extends string> {
  groups: readonly SectionNavGroup<T>[];
  value: T;
  onChange: (id: T) => void;
  /** Accessible name of the tablist, e.g. "Settings sections". */
  label: string;
  /** Tab ids are `${idPrefix}-tab-${id}`, panel ids `${idPrefix}-tabpanel-${id}`. */
  idPrefix: string;
  /** Icon-only column (desktop only). */
  collapsed?: boolean;
  /** Content pinned above the list, e.g. a collapse toggle. */
  header?: React.ReactNode;
  className?: string;
  "data-testid"?: string;
  tourTarget?: string;
}

export function useIsDesktopSectionNav(): boolean {
  const [isDesktop, setIsDesktop] = useState(
    () => typeof window !== "undefined" && window.matchMedia(SECTION_NAV_DESKTOP_QUERY).matches,
  );

  useEffect(() => {
    const media = window.matchMedia(SECTION_NAV_DESKTOP_QUERY);
    const handleChange = (event: MediaQueryListEvent) => setIsDesktop(event.matches);
    setIsDesktop(media.matches);
    media.addEventListener("change", handleChange);
    return () => media.removeEventListener("change", handleChange);
  }, []);

  return isDesktop;
}

export function SectionNav<T extends string>({
  groups,
  value,
  onChange,
  label,
  idPrefix,
  collapsed = false,
  header,
  className,
  "data-testid": testId,
  tourTarget,
}: SectionNavProps<T>) {
  const isDesktop = useIsDesktopSectionNav();
  const listRef = useRef<HTMLDivElement>(null);
  const items = useMemo(() => groups.flatMap((group) => group.items), [groups]);
  const iconOnly = collapsed && isDesktop;

  useEffect(() => {
    const selected = listRef.current?.querySelector<HTMLElement>(`#${idPrefix}-tab-${value}`);
    selected?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [idPrefix, value, isDesktop]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const previousKey = isDesktop ? "ArrowUp" : "ArrowLeft";
      const nextKey = isDesktop ? "ArrowDown" : "ArrowRight";
      if (![previousKey, nextKey, "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const tabs = listRef.current?.querySelectorAll<HTMLButtonElement>("[role='tab']");
      if (!tabs || tabs.length === 0) return;
      const current = Array.from(tabs).indexOf(document.activeElement as HTMLButtonElement);
      const from = current >= 0 ? current : items.findIndex((item) => item.id === value);
      let next: number;
      if (event.key === nextKey) next = (from + 1) % tabs.length;
      else if (event.key === previousKey) next = (from - 1 + tabs.length) % tabs.length;
      else if (event.key === "Home") next = 0;
      else next = tabs.length - 1;
      tabs[next]?.focus();
      const nextItem = items[next];
      if (nextItem) onChange(nextItem.id);
    },
    [isDesktop, items, onChange, value],
  );

  return (
    <nav
      aria-label={label}
      data-testid={testId}
      data-tour-target={tourTarget}
      className={cn(
        "flex min-w-0 shrink-0 flex-col border-b border-border-default bg-surface-base",
        "md:h-full md:border-b-0 md:border-r",
        iconOnly ? "md:w-14" : "md:w-56",
        className,
      )}
    >
      {header ? <div className="hidden md:block">{header}</div> : null}
      <div
        ref={listRef}
        role="tablist"
        aria-label={label}
        aria-orientation={isDesktop ? "vertical" : "horizontal"}
        onKeyDown={handleKeyDown}
        className={cn(
          "flex min-w-0 gap-1 overflow-x-auto px-3 py-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
          "md:flex-1 md:flex-col md:gap-0.5 md:overflow-y-auto md:overflow-x-hidden md:py-3",
          iconOnly && "md:px-2",
        )}
      >
        {groups.map((group, groupIndex) => (
          <React.Fragment key={group.id}>
            {group.label && isDesktop && !iconOnly ? (
              <div
                role="presentation"
                className={cn(
                  "ft-text-overline px-2.5 pb-1 text-text-muted",
                  groupIndex === 0 ? "pt-1" : "pt-4",
                )}
              >
                {group.label}
              </div>
            ) : null}
            {!group.label && groupIndex > 0 && isDesktop ? (
              <div role="presentation" className="mx-2.5 my-2 h-px bg-border-subtle" />
            ) : null}
            {group.items.map((item) => {
              const Icon = item.icon;
              const active = item.id === value;
              const showProgress = !iconOnly && item.progress != null && item.progress > 0;
              return (
                <div key={item.id} className="shrink-0 md:w-full">
                  <button
                    type="button"
                    role="tab"
                    id={`${idPrefix}-tab-${item.id}`}
                    aria-selected={active}
                    aria-controls={active ? `${idPrefix}-tabpanel-${item.id}` : undefined}
                    tabIndex={active ? 0 : -1}
                    title={iconOnly ? item.label : item.title}
                    onClick={() => onChange(item.id)}
                    className={cn(
                      "relative flex h-9 shrink-0 items-center gap-2.5 rounded-md px-2.5 text-left text-sm transition-colors",
                      "md:w-full",
                      iconOnly && "md:justify-center md:px-0",
                      active
                        ? "bg-surface-hover font-medium text-text-primary"
                        : "text-text-secondary hover:bg-surface-hover/60 hover:text-text-primary",
                    )}
                  >
                    {active ? (
                      <span
                        aria-hidden="true"
                        className="absolute left-0 top-1/2 hidden h-4 w-0.5 -translate-y-1/2 rounded-full bg-accent md:block"
                      />
                    ) : null}
                    {Icon ? (
                      <Icon
                        className={cn("size-4 shrink-0", active ? "text-accent" : "text-text-muted")}
                        aria-hidden="true"
                      />
                    ) : null}
                    <span className={cn("truncate whitespace-nowrap", iconOnly && "md:sr-only")}>
                      {item.label}
                    </span>
                    {item.indicator ? (
                      <span className={cn("ml-auto flex shrink-0 items-center", iconOnly && "md:absolute md:right-1.5 md:top-1.5")}>
                        {item.indicator}
                      </span>
                    ) : null}
                  </button>
                  {showProgress ? (
                    <div
                      className="mx-2.5 mb-1 mt-0.5"
                      role="presentation"
                      aria-hidden="true"
                    >
                      <div className="h-0.5 w-full rounded-full bg-border-default/50">
                        <div
                          className="h-full rounded-full bg-accent/60"
                          style={{ width: `${item.progress}%` }}
                        />
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </React.Fragment>
        ))}
      </div>
    </nav>
  );
}
