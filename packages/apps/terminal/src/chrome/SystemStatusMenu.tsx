/**
 * SystemStatusMenu — the one TopBar home for broker, Laya and LLM status.
 *
 * The button carries a single worst-first dot (see summariseDeskStatus); the
 * popover lists broker, Laya and LLM in plain words and the two places to fix
 * them. Feed provenance is not repeated here: it lives at the start of the
 * ticker.
 */

import { useState } from "react";
import { useNavigate } from "react-router";
import { ChevronDown } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { summariseDeskStatus, type DeskStatusTone } from "@/lib/deskStatus";
import { cn } from "@/lib/utils";
import { useModeStore } from "@/stores/modeStore";
import { DeskStatusCluster, useDeskStatus } from "./DeskStatusCluster";

const DOT: Record<DeskStatusTone, string> = {
  ok: "bg-profit",
  warn: "bg-amber-400",
  down: "bg-loss",
  neutral: "bg-text-muted",
};

export default function SystemStatusMenu({ compact = false }: { compact?: boolean }) {
  const navigate = useNavigate();
  const mode = useModeStore((s) => s.mode);
  const status = useDeskStatus();
  const summary = summariseDeskStatus({ mode, ...status });
  const [open, setOpen] = useState(false);

  function go(path: string) {
    setOpen(false);
    navigate(path);
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="system-status-btn"
          data-tone={summary.tone}
          aria-label={`Status: ${summary.label}`}
          className={cn(
            "flex h-8 shrink-0 items-center gap-2 rounded-md px-2.5 text-xs font-medium text-text-secondary transition-colors",
            "hover:bg-surface-hover hover:text-text-primary data-[state=open]:bg-surface-hover data-[state=open]:text-text-primary",
          )}
        >
          <span aria-hidden="true" className={cn("size-2 rounded-full", DOT[summary.tone])} />
          {!compact ? <span>Status</span> : null}
          <ChevronDown className="size-3 text-text-muted" aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={8}
        className="w-80 border-border-default bg-surface-card p-0 text-text-primary shadow-floating"
        data-testid="system-status-panel"
      >
        <div className="border-b border-border-subtle px-4 py-3">
          <p className="text-sm font-semibold text-text-primary">Status</p>
          <p className="mt-0.5 flex items-center gap-2 text-xs text-text-secondary">
            <span aria-hidden="true" className={cn("size-1.5 rounded-full", DOT[summary.tone])} />
            {summary.label}
          </p>
        </div>
        <div className="px-4 py-1">
          <DeskStatusCluster variant="stacked" />
        </div>
        <div className="flex items-center justify-between gap-2 border-t border-border-subtle px-3 py-2">
          <button
            type="button"
            onClick={() => go("/settings#brokers")}
            className="rounded-md px-2 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-surface-hover"
          >
            Manage brokers
          </button>
          <button
            type="button"
            onClick={() => go("/settings#llm")}
            className="rounded-md px-2 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary"
          >
            AI model settings
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
