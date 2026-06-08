/**
 * AIPulseCard — Latest AI insight, regime badge, "Chat with AI" link.
 */

import { BentoCard } from "@/components/bento/BentoCard";
import { Sparkles, MessageSquare } from "lucide-react";
import { DemoBadge } from "./DemoBadge";

export function AIPulseCard() {
  function handleChatWithAI() {
    window.dispatchEvent(new CustomEvent("flinttrade:navigate", { detail: "/ai" }));
  }

  return (
    <BentoCard size="default" label="AI Pulse (example)" data-testid="ai-pulse-card">
      <DemoBadge testId="ai-pulse-demo-badge" label="Example" title="Illustrative example — not a live AI reading. Open the AI tab for real insights." />
      <div className="p-4 h-full flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Sparkles size={13} className="text-accent" aria-hidden="true" />
          <p className="text-[10px] font-medium uppercase tracking-widest text-text-muted">
            AI Pulse
          </p>
        </div>

        {/* Regime badge — illustrative example, not a live regime call */}
        <span className="self-start inline-block px-2 py-0.5 rounded-full text-[11px] font-medium bg-neutral-bg text-text-muted border border-neutral-border">
          Example regime
        </span>

        {/* Illustrative copy — no fabricated level or FII data claim. Real
            insights come from a connected model in the AI tab. */}
        <p className="text-xs text-text-secondary leading-relaxed flex-1">
          Connect a model in the AI tab to generate a live market read, a regime
          call, and trade ideas from your own data — this card shows an example
          of the format, not a live reading.
        </p>

        {/* Chat link */}
        <button
          type="button"
          onClick={handleChatWithAI}
          className="flex items-center gap-1.5 text-[11px] font-medium text-accent hover:opacity-80 transition-colors mt-auto"
          aria-label="Open AI chat"
        >
          <MessageSquare size={12} aria-hidden="true" />
          Chat with AI
        </button>
      </div>
    </BentoCard>
  );
}
