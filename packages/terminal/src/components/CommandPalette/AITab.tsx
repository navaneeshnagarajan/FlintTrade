import { useState } from "react";
import { Sparkles, Send, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAIConversationStore } from "@/stores/aiConversationStore";

interface AITabProps {
  query: string;
  onClose: () => void;
}

const QUICK_PROMPTS = [
  "Analyse NIFTY trend today",
  "What are FII/DII flows?",
  "Summarise my open positions",
  "Best option strategy for sideways market",
];

export function AITab({ query, onClose }: AITabProps) {
  const addMessage = useAIConversationStore((s) => s.addMessage);
  const strippedQuery = query.replace(/^@ai\s*/i, "").trim();
  const [inputValue, setInputValue] = useState(strippedQuery);

  function handleSend(text: string) {
    if (!text.trim()) return;
    addMessage("user", text.trim());
    onClose();
    // Navigate to /ai so the user sees the response
    window.dispatchEvent(
      new CustomEvent("flinttrade:navigate", { detail: { path: "/ai" } }),
    );
  }

  return (
    <div className="flex flex-col gap-3 px-4 py-4">
      {/* Input */}
      <div className="flex items-center gap-2 bg-glass-l2 border border-glass-l2 rounded-glass-control px-3 py-2">
        <Sparkles size={14} className="shrink-0 text-[#8b5cf6]" />
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleSend(inputValue);
            }
          }}
          placeholder="Ask AI anything about your portfolio, markets, strategies…"
          className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-muted outline-none"
          autoFocus
        />
        <button
          type="button"
          onClick={() => handleSend(inputValue)}
          disabled={!inputValue.trim()}
          className={cn(
            "p-1 rounded transition-colors",
            inputValue.trim() ? "text-[#8b5cf6] hover:bg-glass-l3" : "text-text-muted/30",
          )}
        >
          <Send size={14} />
        </button>
      </div>

      {/* Quick prompts */}
      {!strippedQuery && (
        <div className="flex flex-col gap-1">
          <p className="text-[10px] uppercase tracking-widest text-text-muted font-medium px-1">Quick prompts</p>
          {QUICK_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => handleSend(prompt)}
              className="flex items-center gap-2 px-3 py-2 rounded-glass-control text-sm text-text-secondary hover:bg-glass-l2 hover:text-text-primary transition-colors text-left"
            >
              <ArrowRight size={12} className="shrink-0 text-text-muted" />
              {prompt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
