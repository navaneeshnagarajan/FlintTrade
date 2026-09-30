/**
 * One static Mode line under the TopBar.
 *
 * Desk-first: a single tinted line, with horizontal scroll only when the
 * copy cannot fit. Each mode keeps one colour everywhere (Example info blue,
 * Practice amber, Live green). It is Mode chrome, never an outage banner.
 * An example-data session gets a way to create a real account from here.
 */

import { Compass, FlaskConical, Zap } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { modeHonestyCopy } from "@/lib/modeHonesty";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/authStore";
import type { AppMode } from "@/stores/modeStore";

const MODE_STYLE: Record<AppMode, { Icon: LucideIcon; bar: string; icon: string }> = {
  explore: {
    Icon: Compass,
    bar: "border-info/20 bg-info/[0.06]",
    icon: "text-info",
  },
  practice: {
    Icon: FlaskConical,
    bar: "border-amber-500/25 bg-amber-500/[0.08]",
    icon: "text-[var(--color-warning-text,var(--color-warning))]",
  },
  live: {
    Icon: Zap,
    bar: "border-profit/25 bg-profit/[0.08]",
    icon: "text-[var(--color-bullish-text,var(--color-profit))]",
  },
};

function ExampleSessionAction() {
  const navigate = useNavigate();
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={() => navigate("/setup")}
      className="h-6 shrink-0 px-1.5 text-xs text-info hover:bg-info/10 hover:text-info"
      data-testid="mode-bar-setup"
    >
      Create your account →
    </Button>
  );
}

export default function ModeHonestyBar({ mode }: { mode: AppMode }) {
  const line = modeHonestyCopy(mode);
  const { Icon, bar, icon } = MODE_STYLE[mode];
  const exampleSession = useAuthStore((s) => s.token === "demo-user");

  return (
    <div
      data-testid="mode-honesty-bar"
      data-mode={mode}
      className={cn("flex shrink-0 items-center gap-2 border-b px-3 py-1", bar)}
    >
      <Icon className={cn("size-3.5 shrink-0", icon)} aria-hidden="true" />
      <p className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap text-xs text-text-secondary [scrollbar-width:none]">
        {line}
      </p>
      {mode === "explore" && exampleSession ? <ExampleSessionAction /> : null}
    </div>
  );
}
