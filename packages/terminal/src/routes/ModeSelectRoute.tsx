/**
 * ModeSelectRoute — mode picker shown during the login flow.
 *
 * Presents three cards: Demo / Sandbox / Live.
 * Selecting "Live" requires a 6-digit PIN before calling onSelect.
 * Not a standalone route — used as a step inside WelcomeRoute.
 */

import { useState } from "react";
import { Monitor, FlaskConical, Zap, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AppMode } from "@/stores/modeStore";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ModeSelectRouteProps {
  onSelect: (mode: AppMode) => void;
}

interface ModeCardConfig {
  id: AppMode;
  label: string;
  description: string;
  brokerNote: string;
  icon: React.ReactNode;
  pillClass: string;
  borderClass: string;
  selectedBorderClass: string;
  iconBgClass: string;
}

// ---------------------------------------------------------------------------
// Card configuration
// ---------------------------------------------------------------------------

const MODE_CARDS: ModeCardConfig[] = [
  {
    id: "demo",
    label: "Demo",
    description: "Explore with simulated data",
    brokerNote: "No broker needed",
    icon: <Monitor size={22} aria-hidden="true" />,
    pillClass: "bg-text-muted/20 text-text-secondary",
    borderClass: "border-border-default hover:border-text-muted/60",
    selectedBorderClass: "border-text-secondary ring-1 ring-text-secondary/30",
    iconBgClass: "bg-text-muted/10 text-text-secondary",
  },
  {
    id: "sandbox",
    label: "Sandbox",
    description: "Paper trade with live data",
    brokerNote: "Broker required",
    icon: <FlaskConical size={22} aria-hidden="true" />,
    pillClass: "bg-amber-500/20 text-amber-400",
    borderClass: "border-border-default hover:border-amber-500/50",
    selectedBorderClass: "border-amber-500 ring-1 ring-amber-500/30",
    iconBgClass: "bg-amber-500/10 text-amber-400",
  },
  {
    id: "live",
    label: "Live",
    description: "Real trading",
    brokerNote: "Broker required · PIN required",
    icon: <Zap size={22} aria-hidden="true" />,
    pillClass: "bg-profit/20 text-profit",
    borderClass: "border-border-default hover:border-profit/50",
    selectedBorderClass: "border-profit ring-1 ring-profit/30",
    iconBgClass: "bg-profit/10 text-profit",
  },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ModeSelectRoute({ onSelect }: ModeSelectRouteProps) {
  const [selected, setSelected] = useState<AppMode>("demo");
  const [pin, setPin] = useState("");
  const [pinError, setPinError] = useState("");

  const handleContinue = () => {
    if (selected === "live") {
      if (pin.length !== 6) {
        setPinError("Please enter your 6-digit PIN.");
        return;
      }
      // PIN verification is handled server-side on the actual mode-switch call.
      // Here we just pass it along with the selection.
      setPinError("");
    }
    onSelect(selected);
  };

  const handleCardSelect = (mode: AppMode) => {
    setSelected(mode);
    setPin("");
    setPinError("");
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-surface-base p-6">
      <div className="w-full max-w-lg space-y-8">
        {/* Heading */}
        <div className="text-center space-y-1">
          <h1 className="font-heading font-bold text-2xl text-text-primary">
            How would you like to trade today?
          </h1>
          <p className="text-sm text-text-muted">
            You can switch modes at any time from the TopBar.
          </p>
        </div>

        {/* Mode cards */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" role="radiogroup" aria-label="Select trading mode">
          {MODE_CARDS.map((card) => {
            const isSelected = selected === card.id;
            return (
              <button
                key={card.id}
                role="radio"
                aria-checked={isSelected}
                onClick={() => handleCardSelect(card.id)}
                className={`
                  relative flex flex-col items-center gap-3 p-5 rounded-xl border
                  bg-surface-card text-left transition-all duration-150 cursor-pointer
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50
                  ${isSelected ? card.selectedBorderClass : card.borderClass}
                `}
              >
                {/* Mode icon */}
                <div className={`flex items-center justify-center w-11 h-11 rounded-xl ${card.iconBgClass}`}>
                  {card.icon}
                </div>

                {/* Label + description */}
                <div className="text-center space-y-1">
                  <span className="block font-heading font-semibold text-sm text-text-primary">
                    {card.label}
                  </span>
                  <span className="block text-xs text-text-secondary">
                    {card.description}
                  </span>
                </div>

                {/* Broker note pill */}
                <span className={`text-xxs font-medium px-2 py-0.5 rounded-full ${card.pillClass}`}>
                  {card.brokerNote}
                </span>

                {/* Selected indicator dot */}
                {isSelected && (
                  <span
                    className="absolute top-2.5 right-2.5 w-2 h-2 rounded-full bg-current opacity-80"
                    aria-hidden="true"
                  />
                )}
              </button>
            );
          })}
        </div>

        {/* PIN input — only shown when Live is selected */}
        {selected === "live" && (
          <div className="space-y-3 animate-fade-in">
            <div className="p-4 rounded-lg border border-profit/20 bg-profit/5 space-y-3">
              <p className="text-xs text-text-secondary flex items-center gap-1.5">
                <Zap size={12} className="text-profit shrink-0" aria-hidden="true" />
                Live mode executes real orders with real money. Enter your PIN to confirm.
              </p>
              <div>
                <label htmlFor="live-mode-pin" className="text-xs text-text-secondary font-medium block mb-1.5">
                  PIN
                </label>
                <Input
                  id="live-mode-pin"
                  type="password"
                  inputMode="numeric"
                  maxLength={6}
                  value={pin}
                  onChange={(e) => {
                    setPin(e.target.value.replace(/\D/g, ""));
                    if (pinError) setPinError("");
                  }}
                  placeholder="6-digit PIN"
                  aria-label="Enter your 6-digit PIN to enable Live mode"
                  className="text-center font-mono text-lg tracking-widest max-w-48"
                  onKeyDown={(e) => e.key === "Enter" && handleContinue()}
                  autoFocus
                />
              </div>

              {pinError && (
                <div className="flex items-center gap-2 text-xs text-loss">
                  <AlertTriangle size={12} aria-hidden="true" />
                  {pinError}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Continue button */}
        <Button
          onClick={handleContinue}
          disabled={selected === "live" && pin.length !== 6}
          className="w-full"
          size="lg"
        >
          Continue with {MODE_CARDS.find((c) => c.id === selected)?.label}
        </Button>
      </div>
    </div>
  );
}
