/**
 * SkillSection — adaptive skill layer settings panel.
 *
 * Five sub-sections:
 *   1. Global Level — select the app-wide experience level
 *   2. Per-Route Overrides — override level per domain
 *   3. Help Preferences — inline hints, guided tours, AI tutor toggles
 *   4. Activity Metrics — read-only per-domain counters
 *   5. Tour Management — clear completed tours and dismissed hints
 *
 * Uses WCAG-compliant friendly labels ("Getting Started" not "Beginner")
 * to avoid patronizing language.
 */

import { useCallback } from "react";
import {
  GraduationCap,
  TrendingUp,
  PiggyBank,
  BookOpen,
  FlaskConical,
  Workflow,
  Bot,
  X,
  RotateCcw,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { useSkillStore } from "@/stores/skillStore";
import type { SkillLevel, Domain } from "@/types/skill";
import { SectionTitle, SelectInput, Toggle, FieldRow } from "./shared";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const GLOBAL_LEVEL_OPTIONS = [
  { value: "beginner",     label: "Getting Started" },
  { value: "intermediate", label: "Confident"       },
  { value: "advanced",     label: "Expert"          },
];

/** Includes the "use global" sentinel value */
const OVERRIDE_OPTIONS = [
  { value: "",             label: "Global Default"  },
  { value: "beginner",     label: "Getting Started" },
  { value: "intermediate", label: "Confident"       },
  { value: "advanced",     label: "Expert"          },
];

const GLOBAL_LEVEL_DESCRIPTIONS: Record<SkillLevel, string> = {
  beginner:     "Shows beginner hints, guided tour prompts, and simplified views across all modules.",
  intermediate: "Enables more detail, advanced filters, and contextual tooltips without the basics.",
  advanced:     "Full interface with all advanced tools visible. Minimises explanatory copy.",
};

interface DomainDef {
  domain: Domain;
  label: string;
  icon: LucideIcon;
}

const DOMAINS: DomainDef[] = [
  { domain: "trade",    label: "Trade",    icon: TrendingUp   },
  { domain: "invest",   label: "Invest",   icon: PiggyBank    },
  { domain: "learn",    label: "Learn",    icon: BookOpen     },
  { domain: "lab",      label: "Lab",      icon: FlaskConical },
  { domain: "automate", label: "Automate", icon: Workflow     },
  { domain: "ai",       label: "AI",       icon: Bot          },
];

// ---------------------------------------------------------------------------
// MetricCard — read-only display of per-domain counters
// ---------------------------------------------------------------------------

function MetricCard({ domain, icon: Icon, label }: DomainDef) {
  const metrics = useSkillStore((s) => s.metrics[domain]);
  const effectiveLevel = useSkillStore((s) => s.getEffectiveLevel(domain));

  const levelLabel =
    effectiveLevel === "beginner"
      ? "Getting Started"
      : effectiveLevel === "intermediate"
        ? "Confident"
        : "Expert";

  // Convert metrics object to display rows
  const rows = Object.entries(metrics)
    .filter(([key]) => key !== "lastActiveDate")
    .map(([key, val]) => ({
      key,
      label: key
        // camelCase -> "Camel Case"
        .replace(/([A-Z])/g, " $1")
        .replace(/^./, (c) => c.toUpperCase())
        .trim(),
      value: typeof val === "number" ? val : 0,
    }));

  return (
    <div className="p-3 rounded-lg border border-border-default bg-surface-card space-y-2">
      <div className="flex items-center gap-2">
        <Icon size={13} className="text-accent shrink-0" />
        <span className="text-xs font-semibold text-text-primary">{label}</span>
        <span className="ml-auto text-xxs font-mono text-accent/80 bg-accent/10 px-1.5 py-0.5 rounded-full">
          {levelLabel}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        {rows.map(({ key, label: rowLabel, value }) => (
          <div key={key} className="flex justify-between items-center">
            <span className="text-xxs text-text-muted">{rowLabel}</span>
            <span className="text-xxs font-mono tabular-nums text-text-secondary">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 1: Global Level
// ---------------------------------------------------------------------------

function GlobalLevelSection() {
  const globalLevel = useSkillStore((s) => s.globalLevel);
  const setGlobalLevel = useSkillStore((s) => s.setGlobalLevel);

  return (
    <section className="space-y-3" aria-labelledby="skill-global-heading">
      <p id="skill-global-heading" className="text-xs font-semibold uppercase tracking-wider text-text-muted">
        Experience Level
      </p>
      <FieldRow
        label="App-wide level"
        hint={GLOBAL_LEVEL_DESCRIPTIONS[globalLevel]}
        tooltip="This level controls how much detail and how many features are shown across all modules. Individual modules can override this."
      >
        <SelectInput
          value={globalLevel}
          onChange={(v) => setGlobalLevel(v as SkillLevel)}
          options={GLOBAL_LEVEL_OPTIONS}
          aria-label="Global skill level"
        />
      </FieldRow>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Section 2: Per-Route Overrides
// ---------------------------------------------------------------------------

function RouteOverridesSection() {
  const { routeOverrides, setRouteOverride, clearRouteOverride } = useSkillStore(
    useShallow((s) => ({
      routeOverrides:  s.routeOverrides,
      setRouteOverride: s.setRouteOverride,
      clearRouteOverride: s.clearRouteOverride,
    })),
  );

  const handleChange = useCallback(
    (domain: Domain, value: string) => {
      if (!value) {
        clearRouteOverride(domain);
      } else {
        setRouteOverride(domain, value as SkillLevel);
      }
    },
    [setRouteOverride, clearRouteOverride],
  );

  return (
    <section className="space-y-3" aria-labelledby="skill-overrides-heading">
      <p id="skill-overrides-heading" className="text-xs font-semibold uppercase tracking-wider text-text-muted">
        Module Overrides
      </p>
      <p className="text-xs text-text-muted">
        Set a different experience level for a specific module. Leave at Global Default to follow the app-wide setting.
      </p>
      <div className="space-y-2">
        {DOMAINS.map(({ domain, label, icon: Icon }) => {
          const currentOverride = routeOverrides[domain] ?? "";
          const hasOverride = !!routeOverrides[domain];

          return (
            <div
              key={domain}
              className="flex items-center gap-3 px-3 py-2 rounded-lg border border-border-default bg-surface-card hover:bg-surface-hover transition-colors"
            >
              <Icon size={13} className={hasOverride ? "text-accent" : "text-text-muted"} />
              <span className={`text-xs flex-1 ${hasOverride ? "text-text-primary font-medium" : "text-text-secondary"}`}>
                {label}
              </span>
              <div className="w-44">
                <SelectInput
                  value={currentOverride}
                  onChange={(v) => handleChange(domain, v)}
                  options={OVERRIDE_OPTIONS}
                  aria-label={`${label} skill level override`}
                />
              </div>
              {hasOverride && (
                <button
                  type="button"
                  onClick={() => clearRouteOverride(domain)}
                  aria-label={`Clear ${label} override`}
                  title="Clear override"
                  className="h-5 w-5 flex items-center justify-center rounded text-text-muted hover:text-loss hover:bg-loss/10 transition-colors flex-none"
                >
                  <X size={11} />
                </button>
              )}
              {!hasOverride && <div className="w-5 flex-none" />}
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Section 3: Help Preferences
// ---------------------------------------------------------------------------

const HELP_PREF_DETAILS = [
  {
    key: "inlineHints" as const,
    label: "Inline Hints",
    description: 'Shows "?" icons next to form fields and controls. Click to see a plain-language explanation of what the field does.',
  },
  {
    key: "spotlightTours" as const,
    label: "Guided Tours",
    description: "Offers a step-by-step tour when you visit a module for the first time. Tours can be replayed from Tour Management below.",
  },
  {
    key: "aiTutor" as const,
    label: "AI Tutor",
    description: "Shows the floating AI tutor pill in the bottom-right corner. Ask questions about trading concepts or how to use FlintTrade.",
  },
];

function HelpPrefsSection() {
  const { helpPrefs, setHelpPref } = useSkillStore(
    useShallow((s) => ({ helpPrefs: s.helpPrefs, setHelpPref: s.setHelpPref })),
  );

  return (
    <section className="space-y-3" aria-labelledby="skill-helpprefs-heading">
      <p id="skill-helpprefs-heading" className="text-xs font-semibold uppercase tracking-wider text-text-muted">
        Help Preferences
      </p>
      <div className="space-y-4">
        {HELP_PREF_DETAILS.map(({ key, label, description }) => (
          <div key={key} className="space-y-1">
            <Toggle
              checked={helpPrefs[key]}
              onChange={(v) => setHelpPref(key, v)}
              label={label}
            />
            <p className="text-xs text-text-muted pl-9 leading-relaxed">{description}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Section 4: Activity Metrics
// ---------------------------------------------------------------------------

function ActivityMetricsSection() {
  const resetToDefaults = useSkillStore((s) => s.resetToDefaults);

  return (
    <section className="space-y-3" aria-labelledby="skill-metrics-heading">
      <p id="skill-metrics-heading" className="text-xs font-semibold uppercase tracking-wider text-text-muted">
        Activity Metrics
      </p>
      <p className="text-xs text-text-muted">
        These counters track your usage across modules. FlintTrade uses them to suggest when you are ready for more advanced features.
      </p>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {DOMAINS.map((def) => (
          <MetricCard key={def.domain} {...def} />
        ))}
      </div>
      <div className="pt-1">
        <button
          type="button"
          onClick={resetToDefaults}
          className="flex items-center gap-2 px-3 py-1.5 text-xs rounded border border-loss/30 text-loss hover:bg-loss/10 transition-colors"
        >
          <Trash2 size={12} />
          Reset Activity Data
        </button>
        <p className="text-xs text-text-muted mt-1.5">
          Clears all counters and resets your level to Getting Started. This also removes all dismissed upgrade suggestions.
        </p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Section 5: Tour Management
// ---------------------------------------------------------------------------

function TourManagementSection() {
  function replayAllTours() {
    const keys = Object.keys(localStorage).filter((k) =>
      k.startsWith("ft-tour-completed-"),
    );
    keys.forEach((k) => localStorage.removeItem(k));
  }

  function resetDismissedHints() {
    const keys = Object.keys(localStorage).filter((k) =>
      k.startsWith("ft-hint-dismissed-"),
    );
    keys.forEach((k) => localStorage.removeItem(k));
  }

  return (
    <section className="space-y-3" aria-labelledby="skill-tours-heading">
      <p id="skill-tours-heading" className="text-xs font-semibold uppercase tracking-wider text-text-muted">
        Tour Management
      </p>
      <div className="space-y-3">
        <div className="flex items-start gap-4">
          <div className="flex-1 space-y-0.5">
            <p className="text-xs text-text-primary font-medium">Replay All Tours</p>
            <p className="text-xs text-text-muted">
              Clears completion state for every guided tour. Tours will re-appear the next time you visit each module.
            </p>
          </div>
          <button
            type="button"
            onClick={replayAllTours}
            className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-xs rounded border border-border-default text-text-secondary hover:text-text-primary hover:border-accent/40 hover:bg-accent/5 transition-colors"
          >
            <RotateCcw size={12} />
            Replay Tours
          </button>
        </div>
        <div className="flex items-start gap-4">
          <div className="flex-1 space-y-0.5">
            <p className="text-xs text-text-primary font-medium">Reset Dismissed Hints</p>
            <p className="text-xs text-text-muted">
              Re-shows all inline hint icons that were previously dismissed via the "?" popover.
            </p>
          </div>
          <button
            type="button"
            onClick={resetDismissedHints}
            className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-xs rounded border border-border-default text-text-secondary hover:text-text-primary hover:border-accent/40 hover:bg-accent/5 transition-colors"
          >
            <RotateCcw size={12} />
            Reset Hints
          </button>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export function SkillSection() {
  return (
    <div className="space-y-8" aria-label="Skill and experience settings">
      <SectionTitle>
        <span className="flex items-center gap-2">
          <GraduationCap size={14} className="text-accent" />
          Adaptive Skill Layer
        </span>
      </SectionTitle>

      <GlobalLevelSection />

      <div className="border-t border-border-default" />
      <RouteOverridesSection />

      <div className="border-t border-border-default" />
      <HelpPrefsSection />

      <div className="border-t border-border-default" />
      <ActivityMetricsSection />

      <div className="border-t border-border-default" />
      <TourManagementSection />
    </div>
  );
}
