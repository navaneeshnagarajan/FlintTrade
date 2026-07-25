/**
 * ReviewStep — final review/confirmation screen and "done" screen for the setup wizard.
 * Includes LayoutPreview (workspace recommendation) and DoneScreen (completion).
 */

import { CheckCircle, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Persona } from "./PersonaStep";

// ---------------------------------------------------------------------------
// Preset logic
// ---------------------------------------------------------------------------

export function getPresetName(experience: string, interests: string[]): string {
  if (experience === "new") {
    if (interests.includes("trading")) return "learn-then-trade";
    if (interests.includes("investing")) return "invest-lite";
    return "learn-first";
  }
  if (experience === "professional") {
    if (interests.includes("trading")) return "scalper-zone";
    return "power-user";
  }
  // intermediate or fallback
  if (interests.length >= 3) return "full";
  if (interests.includes("investing")) return "invest-diversified";
  return "minimal";
}

/**
 * Maps wizard-internal preset names to the actual preset IDs registered in workspacePresets.ts.
 */
export function mapWizardPreset(wizardPreset: string): string {
  const MAP: Record<string, string> = {
    "learn-first": "market-watch",
    "learn-then-trade": "market-watch",
    "invest-lite": "investor-view",
    "invest-diversified": "investor-view",
    "power-user": "scalper-zone",
    "full": "analysis",
    "minimal": "market-watch",
    "scalper-zone": "scalper-zone",
    "options-desk": "options-desk",
  };
  return MAP[wizardPreset] ?? "market-watch";
}

const PRESET_DESCRIPTIONS: Record<string, string> = {
  "learn-first": "Market Watch workspace — Watchlist, Chart, and Dashboard to get started",
  "learn-then-trade": "Market Watch workspace — overview layout ideal for learning while watching markets",
  "invest-lite": "Investor View — Chart, Watchlist, Holdings, and Dashboard for portfolio tracking",
  "invest-diversified": "Investor View — portfolio overview with holdings, watchlist, and chart",
  "scalper-zone": "Scalper Zone — Chart, Order Pad, DOM / Ladder, Positions, and Scalper for rapid execution",
  "power-user": "Scalper Zone — full-featured layout with all execution and analysis panels",
  "full": "Analysis workspace — Chart, OI Analytics, DOM / Ladder, Positions, and News feed",
  "minimal": "Market Watch workspace — clean layout with essential widgets to get started",
  "options-desk": "Options Desk — Option Chain, Chart, Greeks, Positions, and Straddle",
};

// ---------------------------------------------------------------------------
// LayoutPreview
// ---------------------------------------------------------------------------

interface LayoutPreviewProps {
  experience: string;
  interests: string[];
}

export function LayoutPreview({ experience, interests }: LayoutPreviewProps) {
  const wizardPreset = getPresetName(experience, interests);
  const actualPresetId = mapWizardPreset(wizardPreset);
  const description = PRESET_DESCRIPTIONS[wizardPreset] ?? "Custom workspace layout";
  const displayName = actualPresetId
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");

  return (
    <div className="bg-surface-card border border-border-default rounded-lg p-4 shadow-sm space-y-2">
      <p className="text-xxs uppercase tracking-wider text-text-muted">Your workspace</p>
      <p className="text-text-primary font-heading font-bold text-lg">{displayName}</p>
      <p className="text-sm text-text-secondary leading-relaxed">{description}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DoneScreen
// ---------------------------------------------------------------------------

interface DoneScreenProps {
  persona: Persona;
  name: string;
  onGo: () => void;
}

export function DoneScreen({ persona, name, onGo }: DoneScreenProps) {
  const personaLabel =
    persona === "investor" ? "Investor" : persona === "beginner" ? "Learner" : "Trader";

  const destination =
    persona === "investor"
      ? "Investment Dashboard"
      : persona === "beginner"
        ? "Learning Workspace"
        : "Trading Terminal";

  const greeting = name && name !== "Trader" ? `${name}, your` : "Your";

  return (
    <div className="text-center space-y-6 py-4">
      <div className="inline-flex items-center justify-center size-16 rounded-full bg-profit/15 border border-profit/30">
        <CheckCircle className="size-8 text-profit" />
      </div>
      <div className="space-y-2">
        <h3 className="font-heading font-bold text-lg text-text-primary">Setup Complete</h3>
        <p className="text-sm text-text-secondary">
          {greeting} workspace is configured for{" "}
          <span className="text-accent font-medium">{personaLabel}</span>.
        </p>
        <p className="text-text-muted text-xxs">Opening {destination}</p>
      </div>
      <Button
        onClick={onGo}
        className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
        size="lg"
      >
        Launch FlintTrade
        <ArrowRight className="size-4 ml-2" />
      </Button>
    </div>
  );
}
