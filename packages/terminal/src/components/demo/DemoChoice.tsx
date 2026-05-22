/**
 * DemoChoice — shown on first entry to Demo mode.
 *
 * Presents two options:
 *   - Free Explore: jump in with simulated data
 *   - Guided Tour:  step-by-step walkthrough
 *
 * Persists the choice in sessionStorage so the prompt is only shown once
 * per browser session.
 */

import { useState, useEffect } from "react";
import { Compass, GraduationCap } from "lucide-react";
import PublicRouteShell from "@/components/layout/PublicRouteShell";
import { ShimmerButton } from "@/components/magicui/shimmer-button";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type DemoChoiceValue = "explore" | "tour";

interface DemoChoiceProps {
  onChoice: (choice: DemoChoiceValue) => void;
}

interface ChoiceCardConfig {
  id: DemoChoiceValue;
  label: string;
  description: string;
  icon: React.ReactNode;
  borderClass: string;
  selectedBorderClass: string;
  iconBgClass: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SESSION_KEY = "flinttrade:demo-choice-shown";

const CHOICE_CARDS: ChoiceCardConfig[] = [
  {
    id: "explore",
    label: "Free Explore",
    description: "Jump in with simulated data, explore at your own pace",
    icon: <Compass size={24} aria-hidden="true" />,
    borderClass: "border-border-default/70 hover:border-accent/40",
    selectedBorderClass: "border-accent/70 ring-1 ring-accent/30 shadow-[0_0_34px_rgba(34,197,94,0.14)]",
    iconBgClass: "bg-text-muted/10 text-text-secondary",
  },
  {
    id: "tour",
    label: "Guided Tour",
    description: "Step-by-step walkthrough of every feature",
    icon: <GraduationCap size={24} aria-hidden="true" />,
    borderClass: "border-border-default/70 hover:border-accent/50",
    selectedBorderClass: "border-accent ring-1 ring-accent/30 shadow-[0_0_34px_rgba(34,197,94,0.14)]",
    iconBgClass: "bg-accent/10 text-accent",
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns true if the demo choice has already been made this session. */
export function hasMadeDemoChoice(): boolean {
  try {
    return sessionStorage.getItem(SESSION_KEY) !== null;
  } catch {
    return false;
  }
}

/** Marks the demo choice as made so the prompt is not shown again. */
function markDemoChoiceMade(choice: DemoChoiceValue): void {
  try {
    sessionStorage.setItem(SESSION_KEY, choice);
  } catch {
    // sessionStorage unavailable — proceed silently
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DemoChoice({ onChoice }: DemoChoiceProps) {
  const [selected, setSelected] = useState<DemoChoiceValue>("explore");

  // If the choice was already made this session, skip the UI immediately.
  useEffect(() => {
    if (hasMadeDemoChoice()) {
      const stored = sessionStorage.getItem(SESSION_KEY) as DemoChoiceValue | null;
      onChoice(stored ?? "explore");
    }
  }, [onChoice]);

  const handleConfirm = () => {
    markDemoChoiceMade(selected);
    onChoice(selected);
  };

  return (
    <PublicRouteShell
      mainLabel="Explore mode entry"
      maxWidth="md"
      eyebrow="Explore Mode"
      title="How would you like to explore FlintTrade?"
      subtitle="You are in Explore mode - no real data or orders."
    >
      <div className="mx-auto max-w-2xl space-y-6">
        {/* Choice cards */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Explore mode entry choice">
          {CHOICE_CARDS.map((card) => {
            const isSelected = selected === card.id;
            return (
              <button
                key={card.id}
                role="radio"
                aria-checked={isSelected}
                onClick={() => setSelected(card.id)}
                className={`
                  flex min-h-44 flex-col items-center justify-center gap-3 rounded-xl border p-5
                  bg-surface-card/60 shadow-xl shadow-black/10 backdrop-blur-xl transition-all duration-150 cursor-pointer
                  hover:-translate-y-0.5 hover:bg-surface-card/75
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50
                  ${isSelected ? card.selectedBorderClass : card.borderClass}
                `}
              >
                {/* Icon */}
                <div className={`flex size-11 items-center justify-center rounded-md ${card.iconBgClass}`}>
                  {card.icon}
                </div>

                {/* Text */}
                <div className="text-center space-y-1">
                  <span className="block font-heading font-semibold text-sm text-text-primary">
                    {card.label}
                  </span>
                  <span className="block text-xs text-text-secondary">
                    {card.description}
                  </span>
                </div>
              </button>
            );
          })}
        </div>

        {/* Confirm button */}
        <ShimmerButton
          onClick={handleConfirm}
          shimmerColor="#22c55e"
          className="w-full justify-center px-6 py-3 text-sm font-semibold bg-profit/10 border-profit/45 text-profit hover:shadow-[0_0_28px_rgba(34,197,94,0.28)]"
        >
          {selected === "tour" ? "Start Guided Tour" : "Start Exploring"}
        </ShimmerButton>
      </div>
    </PublicRouteShell>
  );
}
