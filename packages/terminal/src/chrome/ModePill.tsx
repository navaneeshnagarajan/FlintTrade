/**
 * ModePill — TopBar pill showing the current execution mode.
 *
 * Colours:
 *   Demo    → grey
 *   Sandbox → amber
 *   Live    → green
 *
 * Clicking opens a DropdownMenu to switch modes.
 * Switching to Live requires PIN via window.prompt (temporary — full PIN
 * dialog is implemented in a later task).
 */

import { Monitor, FlaskConical, Zap } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useModeStore } from "@/stores/modeStore";
import type { AppMode } from "@/stores/modeStore";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

interface ModeConfig {
  label: string;
  pillClass: string;
  icon: React.ReactNode;
}

const MODE_CONFIG: Record<AppMode, ModeConfig> = {
  demo: {
    label: "DEMO",
    pillClass:
      "bg-text-muted/20 text-text-secondary border border-text-muted/20 hover:bg-text-muted/30",
    icon: <Monitor size={11} aria-hidden="true" />,
  },
  sandbox: {
    label: "SANDBOX",
    pillClass:
      "bg-amber-500/15 text-amber-400 border border-amber-500/30 hover:bg-amber-500/25",
    icon: <FlaskConical size={11} aria-hidden="true" />,
  },
  live: {
    label: "LIVE",
    pillClass:
      "bg-profit/15 text-profit border border-profit/30 hover:bg-profit/25",
    icon: <Zap size={11} aria-hidden="true" />,
  },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ModePill() {
  const mode = useModeStore((s) => s.mode);
  const setMode = useModeStore((s) => s.setMode);
  const requiresPinForMode = useModeStore((s) => s.requiresPinForMode);

  const config = MODE_CONFIG[mode];

  const handleSelect = (target: AppMode) => {
    if (target === mode) return;

    if (requiresPinForMode(target)) {
      // Temporary PIN gate — full PIN dialog implemented in later task.
      const entered = window.prompt("Enter your PIN to switch to Live mode:");
      if (!entered || entered.length !== 6 || /\D/.test(entered)) {
        return;
      }
    }

    setMode(target);
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          aria-label={`Current mode: ${config.label}. Click to switch mode.`}
          className={`
            flex items-center gap-1 h-7 px-2 rounded text-xs font-medium font-heading
            transition-colors cursor-pointer
            ${config.pillClass}
          `}
        >
          {config.icon}
          {config.label}
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-44">
        <DropdownMenuItem
          onClick={() => handleSelect("demo")}
          className={mode === "demo" ? "bg-accent/10 text-accent font-medium" : ""}
          aria-current={mode === "demo" ? "true" : undefined}
        >
          <Monitor size={14} className="mr-2 text-text-muted" aria-hidden="true" />
          Demo
          {mode === "demo" && (
            <span className="ml-auto text-xxs text-text-muted">Active</span>
          )}
        </DropdownMenuItem>

        <DropdownMenuItem
          onClick={() => handleSelect("sandbox")}
          className={mode === "sandbox" ? "bg-accent/10 text-accent font-medium" : ""}
          aria-current={mode === "sandbox" ? "true" : undefined}
        >
          <FlaskConical size={14} className="mr-2 text-amber-400" aria-hidden="true" />
          Sandbox
          {mode === "sandbox" && (
            <span className="ml-auto text-xxs text-text-muted">Active</span>
          )}
        </DropdownMenuItem>

        <DropdownMenuSeparator />

        <DropdownMenuItem
          onClick={() => handleSelect("live")}
          className={mode === "live" ? "bg-accent/10 text-accent font-medium" : ""}
          aria-current={mode === "live" ? "true" : undefined}
        >
          <Zap size={14} className="mr-2 text-profit" aria-hidden="true" />
          Live
          {mode === "live" ? (
            <span className="ml-auto text-xxs text-text-muted">Active</span>
          ) : (
            <span className="ml-auto text-xxs text-text-muted">PIN req.</span>
          )}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
