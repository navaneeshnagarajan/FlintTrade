/**
 * Shared UI primitives used across Automate sections.
 * Kept small — only truly reused pieces live here.
 */

import { useEffect, useCallback, useState } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";

// ---------------------------------------------------------------------------
// CSS keyframes — injected once at module load
// ---------------------------------------------------------------------------

const PULSE_STYLES = `
@keyframes ft-pulse-green {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-profit) 40%, transparent); }
  50%       { opacity: 0.7; box-shadow: 0 0 0 4px transparent; }
}
@keyframes ft-pulse-red {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-loss) 50%, transparent); }
  50%       { opacity: 0.6; box-shadow: 0 0 0 5px transparent; }
}
.ft-dot-running {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--color-profit);
  animation: ft-pulse-green 1.6s ease-in-out infinite;
  flex-shrink: 0;
}
.ft-dot-paused {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--color-warning);
  flex-shrink: 0;
}
.ft-dot-kill {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--color-loss);
  animation: ft-pulse-red 1s ease-in-out infinite;
  flex-shrink: 0;
}
`;

if (typeof document !== "undefined") {
  const styleId = "ft-automate-pulse";
  if (!document.getElementById(styleId)) {
    const el = document.createElement("style");
    el.id = styleId;
    el.textContent = PULSE_STYLES;
    document.head.appendChild(el);
  }
}

// ---------------------------------------------------------------------------
// InlineToast
// ---------------------------------------------------------------------------

interface InlineToastProps {
  message: string;
  variant?: "success" | "error";
  onDismiss: () => void;
}

export function InlineToast({ message, variant = "success", onDismiss }: InlineToastProps) {
  useEffect(() => {
    const id = setTimeout(onDismiss, 3000);
    return () => clearTimeout(id);
  }, [onDismiss]);

  const cls =
    variant === "error"
      ? "bg-loss/10 border-loss/20 text-loss"
      : "bg-profit/10 border-profit/20 text-profit";

  return (
    <div
      role={variant === "error" ? "alert" : "status"}
      aria-live={variant === "error" ? "assertive" : "polite"}
      aria-atomic="true"
      className={`flex items-center gap-2 px-3 py-2 rounded text-xs border ${cls}`}
    >
      {variant === "error"
        ? <AlertTriangle size={13} className="flex-none" />
        : <CheckCircle2 size={13} className="flex-none" />}
      <span>{message}</span>
    </div>
  );
}

/** Convenience hook: toast state + auto-dismiss callback */
export function useInlineToast() {
  const [toast, setToast] = useState<{ msg: string; variant: "success" | "error" } | null>(null);
  const dismissToast = useCallback(() => setToast(null), []);
  return { toast, setToast, dismissToast };
}

// ---------------------------------------------------------------------------
// StatusDot / StatusBadge — for cron jobs
// ---------------------------------------------------------------------------

export function StatusDot({ status }: { status: string }) {
  const lower = status.toLowerCase();
  if (lower === "active") return <span className="ft-dot-running" />;
  if (lower === "paused") return <span className="ft-dot-paused" />;
  if (lower === "error")  return <span className="ft-dot-kill" />;
  return <span className="ft-dot-paused" style={{ background: "var(--color-text-muted)" }} />;
}

export function StatusBadge({ status }: { status: string }) {
  const lower = status.toLowerCase();
  if (lower === "active") return <Badge className="text-xs bg-profit/10 text-profit border-0">Active</Badge>;
  if (lower === "paused") return <Badge className="text-xs bg-atm-bg text-warning border-0">Paused</Badge>;
  if (lower === "error")  return <Badge className="text-xs bg-loss/10 text-loss border-0">Error</Badge>;
  return <Badge className="text-xs bg-text-muted/10 text-text-muted border-0">{status}</Badge>;
}

// ---------------------------------------------------------------------------
// VerdictBadge — for audit logs
// ---------------------------------------------------------------------------

export function verdictClass(verdict: string): string {
  const lower = verdict.toLowerCase();
  if (lower === "pass") return "text-profit";
  if (lower === "fail") return "text-loss";
  if (lower === "warn") return "text-warning";
  return "text-text-muted";
}

export function VerdictBadge({ verdict }: { verdict: string }) {
  const lower = verdict.toLowerCase();
  if (lower === "pass") return <Badge className="text-xs bg-profit/10 text-profit border-0">PASS</Badge>;
  if (lower === "fail") return <Badge className="text-xs bg-loss/10 text-loss border-0">FAIL</Badge>;
  if (lower === "warn") return <Badge className="text-xs bg-atm-bg text-warning border-0">WARN</Badge>;
  return <Badge className="text-xs bg-text-muted/10 text-text-muted border-0">{verdict}</Badge>;
}
