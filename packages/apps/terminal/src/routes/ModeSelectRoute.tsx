/**
 * ModeSelectRoute — mode picker shown during the login flow.
 *
 * Presents three cards: Explore / Practice / Live.
 * Selecting "Live" verifies the 6-digit PIN before calling onSelect.
 * Not a standalone route — used as a step inside WelcomeRoute.
 */

import { useState } from "react";
import { Monitor, FlaskConical, Zap, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AppMode } from "@/stores/modeStore";
import { unlockWithPin } from "@/lib/modeAuth";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ModeSelectRouteProps {
  onSelect: (mode: AppMode, liveSessionToken?: string) => void;
  /** Valid canonical deep links may preselect a mode, but never submit it. */
  initialMode?: AppMode;
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
    id: "explore",
    label: "Explore",
    description: "Browse with sample data",
    brokerNote: "No broker needed",
    icon: <Monitor size={22} aria-hidden="true" />,
    pillClass: "bg-text-muted/20 text-text-secondary",
    borderClass: "border-border-default/70 hover:border-text-muted/60",
    selectedBorderClass: "border-text-secondary ring-1 ring-text-secondary/30 shadow-[0_0_30px_rgba(148,163,184,0.16)]",
    iconBgClass: "bg-text-muted/10 text-text-secondary",
  },
  {
    id: "practice",
    label: "Practice",
    // "with live data" overpromised: without a broker or OpenAlgo connection
    // there is no market feed, so a fresh install sees honest dashes and the
    // sandbox refuses market fills (no LTP). Say what actually happens.
    description: "Practice trading with virtual capital",
    // Practice orders run against the native SandboxEngine, never a broker —
    // claiming "Broker required" here scared off broker-less users (item 2).
    brokerNote: "No broker needed · Live prices once one is connected",
    icon: <FlaskConical size={22} aria-hidden="true" />,
    pillClass: "bg-amber-500/20 text-amber-400",
    borderClass: "border-border-default/70 hover:border-amber-500/50",
    selectedBorderClass: "border-amber-500 ring-1 ring-amber-500/30 shadow-[0_0_30px_rgba(245,158,11,0.16)]",
    iconBgClass: "bg-amber-500/10 text-amber-400",
  },
  {
    id: "live",
    label: "Live",
    description: "Real trading",
    brokerNote: "Broker required · PIN required",
    icon: <Zap size={22} aria-hidden="true" />,
    pillClass: "bg-profit/20 text-profit",
    borderClass: "border-border-default/70 hover:border-profit/50",
    selectedBorderClass: "border-profit ring-1 ring-profit/30 shadow-[0_0_30px_rgba(34,197,94,0.16)]",
    iconBgClass: "bg-profit/10 text-profit",
  },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ModeSelectRoute({ onSelect, initialMode = "explore" }: ModeSelectRouteProps) {
  const [selected, setSelected] = useState<AppMode>(initialMode);
  const [pin, setPin] = useState("");
  const [pinError, setPinError] = useState("");
  const [isVerifyingPin, setIsVerifyingPin] = useState(false);

  const handleContinue = async () => {
    if (selected === "live") {
      if (pin.length !== 6 || /\D/.test(pin)) {
        setPinError("Please enter your 6-digit PIN.");
        return;
      }
      setIsVerifyingPin(true);
      try {
        const { token: liveSessionToken } = await unlockWithPin(pin, "live");
        setPinError("");
        onSelect(selected, liveSessionToken);
        return;
      } catch (e) {
        // Surface the backend's actual reason — a wrong PIN says "Invalid PIN",
        // but a missing/expired session (D6) says to sign in first; the old
        // blanket "Incorrect PIN" mislabelled the latter.
        setPinError(e instanceof Error && e.message ? e.message : "Incorrect PIN. Try again.");
        return;
      } finally {
        setIsVerifyingPin(false);
      }
    }
    onSelect(selected);
  };

  const handleCardSelect = (mode: AppMode) => {
    setSelected(mode);
    setPin("");
    setPinError("");
  };

  return (
    <div className="flex items-center justify-center">
      <div className="w-full space-y-6">
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
                  relative flex min-h-40 flex-col items-center justify-center gap-3 rounded-xl border p-4
                  bg-surface-card/60 text-left shadow-xl shadow-black/10 backdrop-blur-xl transition-all duration-150 cursor-pointer
                  hover:-translate-y-0.5 hover:bg-surface-card/75
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50
                  ${isSelected ? card.selectedBorderClass : card.borderClass}
                `}
              >
                {/* Mode icon */}
                <div className={`flex size-10 items-center justify-center rounded-md ${card.iconBgClass}`}>
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
            <div className="space-y-3 rounded-xl border border-profit/25 bg-profit/8 p-4 shadow-xl shadow-black/10 backdrop-blur-xl">
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
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void handleContinue();
                  }}
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
          onClick={() => void handleContinue()}
          disabled={isVerifyingPin || (selected === "live" && pin.length !== 6)}
          className="w-full"
          size="lg"
        >
          {isVerifyingPin ? "Verifying PIN..." : `Continue with ${MODE_CARDS.find((c) => c.id === selected)?.label}`}
        </Button>
      </div>
    </div>
  );
}
