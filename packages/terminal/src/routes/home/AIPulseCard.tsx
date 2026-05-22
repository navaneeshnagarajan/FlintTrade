/**
 * AIPulseCard — Latest AI insight, regime badge, "Chat with AI" link.
 */

import { BentoCard } from "@/components/bento/BentoCard";
import { Sparkles, MessageSquare } from "lucide-react";

export function AIPulseCard() {
  function handleChatWithAI() {
    window.dispatchEvent(new CustomEvent("flinttrade:navigate", { detail: "/ai" }));
  }

  return (
    <BentoCard size="default" label="AI Pulse" data-testid="ai-pulse-card">
      <div className="p-4 h-full flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Sparkles size={13} className="text-accent" aria-hidden="true" />
          <p className="text-[10px] font-medium uppercase tracking-widest text-text-muted">
            AI Pulse
          </p>
        </div>

        {/* Regime badge */}
        <span className="self-start inline-block px-2 py-0.5 rounded-full text-[11px] font-medium bg-neutral-bg text-text-primary border border-neutral-border">
          Sideways
        </span>

        {/* Latest insight */}
        <p className="text-xs text-text-secondary leading-relaxed flex-1">
          Markets are consolidating near key support. FII net flows are neutral. Watch for breakout on NIFTY 50 above 22,500.
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
