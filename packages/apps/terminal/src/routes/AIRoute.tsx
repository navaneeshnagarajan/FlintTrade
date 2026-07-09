import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { useSkillLevel } from "@/hooks/useSkillLevel";
import { useSkillStore } from "@/stores/skillStore";
import { useAIConversationStore } from "@/stores/aiConversationStore";
import { useAuthStore } from "@/stores/authStore";
import { SpotlightTour } from "@/components/help/SpotlightTour";
import { TOUR_DEFINITIONS } from "@/lib/tourDefinitions";
import { useQuery, useMutation } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  Bot,
  Lightbulb,
  MessageSquare,
  Zap,
  TrendingUp,
  BookOpen,
  Settings2,
  RefreshCw,
  Search,
  AlertCircle,
  Loader2,
  CheckCircle2,
  X,
  BarChart2,
  Activity,
  Share2,
  Check,
} from "lucide-react";
import AIAdvisorWidget from "@/widgets/utility/AIAdvisor/AIAdvisorWidget";
import AISuggestionsPanel from "@/routes/ai/AISuggestionsPanel";
import SentimentPanel from "@/routes/ai/SentimentPanel";
import RegimePanel from "@/routes/ai/RegimePanel";
import AgentPanel from "@/routes/ai/AgentPanel";
import { getBase } from "@/services/ftApi.helpers";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  getRecentSignals,
  analyzeSentiment,
  queryKnowledge,
  type Signal,
  type LiveSignal,
  type SentimentResult,
  type RAGResult,
} from "@/services/ftApi";
import { motionConfig, EASE_ENTER, DURATION } from "@/lib/motion";
import { AdvisorStatusResponseSchema } from "@/lib/schemas/ftApi";
import type { AdvisorStatusData } from "@/lib/schemas/ftApi";

// ---------------------------------------------------------------------------
// Section registry
// ---------------------------------------------------------------------------

type SectionId =
  | "chat"
  | "suggestions"
  | "signals"
  | "sentiment"
  | "knowledge"
  | "settings"
  | "market-sentiment"
  | "regime"
  | "agent";

interface SectionDef {
  id: SectionId;
  label: string;
  icon: typeof MessageSquare;
}

const SECTIONS: SectionDef[] = [
  { id: "chat", label: "Chat", icon: MessageSquare },
  { id: "agent", label: "Agent", icon: Bot },
  { id: "suggestions", label: "Suggest", icon: Lightbulb },
  { id: "signals", label: "Signals", icon: Zap },
  { id: "market-sentiment", label: "Market", icon: BarChart2 },
  { id: "regime", label: "Regime", icon: Activity },
  { id: "sentiment", label: "Sentiment", icon: TrendingUp },
  { id: "knowledge", label: "KB", icon: BookOpen },
  { id: "settings", label: "Settings", icon: Settings2 },
];

// Sections that appear as right-side overlay panels (not full-height)
const OVERLAY_SECTIONS = new Set<SectionId>([
  "suggestions",
  "signals",
  "market-sentiment",
  "regime",
  "sentiment",
  "knowledge",
  "settings",
]);

// ---------------------------------------------------------------------------
// Section: Chat — full height, no chrome
// ---------------------------------------------------------------------------

function ChatSection() {
  return (
    <div className="h-full" data-tour-target="ai-chat">
      <AIAdvisorWidget />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Signals — enhanced signal cards with animated confidence bar
// ---------------------------------------------------------------------------

function signalBadgeClass(type: Signal["signal_type"]): string {
  if (type === "BUY") return "bg-bullish-bg text-profit border-profit/30";
  if (type === "SELL") return "bg-bearish-bg text-loss border-loss/30";
  return "bg-surface-base text-text-muted border-border-default";
}

function signalBarColor(type: Signal["signal_type"]): string {
  if (type === "BUY") return "bg-profit";
  if (type === "SELL") return "bg-loss";
  return "bg-text-muted";
}

function SignalCard({ signal, index }: { signal: Signal; index: number }) {
  const indicatorEntries = Object.entries(signal.indicators);
  const pct = signal.confidence * 100;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionConfig.stagger(index)}
    >
      <Card className="bg-surface-card border border-border-default rounded-lg p-4 space-y-3">
        {/* Header row: symbol + direction badge */}
        <div className="flex items-center justify-between">
          <div className="flex items-baseline gap-2">
            <span className="font-mono font-bold text-text-primary text-sm leading-none">
              {signal.symbol}
            </span>
            <span className="text-xs text-text-muted">{signal.exchange}</span>
          </div>
          <Badge
            className={`text-xs font-bold px-2 py-0.5 border rounded-full ${signalBadgeClass(signal.signal_type)}`}
          >
            {signal.signal_type === "BUY"
              ? "Bullish"
              : signal.signal_type === "SELL"
                ? "Bearish"
                : "Hold"}
          </Badge>
        </div>

        {/* Animated confidence bar */}
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-text-muted">
            <span>Confidence</span>
            <span className="font-mono">{Math.round(pct)}%</span>
          </div>
          <div className="h-1.5 bg-surface-base rounded-full overflow-hidden">
            <motion.div
              className={`h-full rounded-full ${signalBarColor(signal.signal_type)}`}
              initial={{ width: "0%" }}
              animate={{ width: `${pct}%` }}
              transition={{
                duration: DURATION.slow,
                ease: EASE_ENTER,
                delay: index * 0.05 + 0.1,
              }}
            />
          </div>
        </div>

        {/* Indicator chips */}
        {indicatorEntries.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {indicatorEntries.map(([key, val]) => (
              <span
                key={key}
                className="text-xs bg-surface-base border border-border-default rounded px-2 py-0.5 font-mono text-text-secondary"
              >
                {key}: {typeof val === "number" ? val.toFixed(2) : String(val)}
              </span>
            ))}
          </div>
        )}

        <p className="text-xs text-text-muted">
          {new Date(signal.timestamp).toLocaleString("en-IN", {
            dateStyle: "short",
            timeStyle: "short",
          })}
        </p>
      </Card>
    </motion.div>
  );
}

// Adapt the working /signals/recent payload (LiveSignal: single indicator+value)
// to the SignalCard's Signal shape (indicators as a Record). LiveSignal has no
// exchange and may carry an "ALERT" type, which maps to "HOLD" for display.
function liveSignalToSignal(ls: LiveSignal): Signal {
  return {
    symbol: ls.symbol,
    exchange: "",
    signal_type: ls.signal_type === "ALERT" ? "HOLD" : ls.signal_type,
    confidence: ls.confidence,
    timestamp: ls.timestamp,
    indicators: { [ls.indicator]: ls.value },
  };
}

function SignalsSection() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["signals"],
    // /signals/active reads a _signal_pipeline that is never wired (always []);
    // /signals/recent is the working ML-signal source (audit M9/M10).
    queryFn: () => getRecentSignals(20),
    refetchInterval: 30_000,
  });

  const signals: Signal[] = (data?.signals ?? []).map(liveSignalToSignal);

  return (
    <div className="space-y-4" data-tour-target="ai-signals">
      <Card className="bg-surface-card border border-border-default rounded-lg p-5">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-heading font-semibold text-base text-text-primary">
            ML-Powered Signals
          </h3>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            disabled={isLoading}
            className="text-text-muted hover:text-text-primary gap-1.5 h-7 text-xs"
          >
            <RefreshCw className={`w-3 h-3 ${isLoading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
        <p className="text-xs text-text-secondary leading-relaxed">
          LightGBM models analyse price, volume, OI, and technicals. Auto-refreshes every 30s.
        </p>
      </Card>

      {isLoading && (
        <div className="flex items-center gap-2 text-text-muted text-sm py-6 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
          Fetching signals...
        </div>
      )}

      {isError && (
        <Card className="bg-surface-card border border-bearish-border rounded-lg p-4">
          <div className="flex items-center gap-2 text-loss text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>Signal service unavailable.</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            className="mt-2 text-text-muted hover:text-text-primary text-xs"
          >
            Retry
          </Button>
        </Card>
      )}

      {!isLoading && !isError && signals.length === 0 && (
        <Card className="bg-surface-card border border-border-default rounded-lg p-6 text-center">
          <Zap className="w-7 h-7 text-text-muted mx-auto mb-2" />
          <p className="text-sm text-text-secondary">No active signals.</p>
          <p className="text-xs text-text-muted mt-1">
            Signal pipeline generates signals during market hours.
          </p>
        </Card>
      )}

      {!isLoading && !isError && signals.length > 0 && (
        <div className="space-y-3">
          {signals.map((signal, idx) => (
            <SignalCard
              key={`${signal.symbol}-${signal.timestamp}-${idx}`}
              signal={signal}
              index={idx}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Sentiment
// ---------------------------------------------------------------------------

function scoreToColor(score: number): string {
  if (score > 0.1) return "text-profit";
  if (score < -0.1) return "text-loss";
  return "text-warning";
}

function labelBadgeClass(label: SentimentResult["label"]): string {
  if (label === "bullish") return "bg-bullish-bg text-profit";
  if (label === "bearish") return "bg-bearish-bg text-loss";
  return "bg-atm-bg text-warning";
}

function SentimentResultCard({ result }: { result: SentimentResult }) {
  const pct = Math.round(Math.abs(result.score) * 100);
  const gaugeWidth = Math.round(((result.score + 1) / 2) * 100);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionConfig.transitions.tab}
    >
      <Card className="bg-surface-card border border-border-default rounded-lg p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-text-muted mb-0.5">Sentiment Score</p>
            <p className={`text-3xl font-mono font-bold ${scoreToColor(result.score)}`}>
              {result.score >= 0 ? "+" : ""}
              {result.score.toFixed(3)}
            </p>
          </div>
          <div className="text-right">
            <Badge className={`text-xs font-semibold mb-1 ${labelBadgeClass(result.label)}`}>
              {result.label.toUpperCase()}
            </Badge>
            <p className="text-xs text-text-muted">
              {Math.round(result.confidence * 100)}% confidence
            </p>
          </div>
        </div>

        {/* Score gauge (-1 to +1) */}
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-text-muted">
            <span>Bearish -1</span>
            <span>Neutral 0</span>
            <span>+1 Bullish</span>
          </div>
          <div className="relative h-2 bg-surface-base rounded-full overflow-hidden">
            <div className="absolute left-1/2 top-0 w-px h-full bg-border-default" />
            <div
              className={`absolute top-0 h-full rounded-full transition-[width,colors] ${
                result.score > 0.1
                  ? "bg-profit"
                  : result.score < -0.1
                    ? "bg-loss"
                    : "bg-warning"
              }`}
              style={{
                left: "50%",
                width: `${pct / 2}%`,
                transform: result.score < 0 ? "translateX(-100%)" : undefined,
              }}
            />
          </div>
          <div
            className="relative h-0"
            style={{ marginLeft: `${gaugeWidth}%`, transform: "translateX(-50%)" }}
          >
            <div className={`text-xs font-mono font-bold leading-none ${scoreToColor(result.score)}`}>
              ▲
            </div>
          </div>
        </div>
      </Card>
    </motion.div>
  );
}

function SentimentSection() {
  const [text, setText] = useState("");
  const [symbol, setSymbol] = useState("");

  const mutation = useMutation({
    mutationFn: (input: string) => analyzeSentiment(input),
  });

  function handleAnalyze() {
    const input = text.trim();
    if (!input) return;
    mutation.mutate(input);
  }

  function handleSymbolSentiment() {
    const sym = symbol.trim().toUpperCase();
    if (!sym) return;
    const query = `Market sentiment and latest news analysis for ${sym} listed on Indian stock exchange NSE/BSE.`;
    mutation.mutate(query);
  }

  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-5">
        <h3 className="font-heading font-semibold text-base text-text-primary mb-2">
          Sentiment Analysis
        </h3>
        <p className="text-xs text-text-secondary leading-relaxed">
          Paste news or any financial text to score market sentiment (-1 bearish to +1 bullish).
          Computed locally via the LLM for full privacy.
        </p>
      </Card>

      {/* Quick symbol lookup */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-4 space-y-3">
        <h4 className="text-sm font-semibold text-text-primary">Quick Symbol Sentiment</h4>
        <div className="flex gap-2">
          <Input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="e.g. NIFTY, RELIANCE"
            aria-label="Symbol for sentiment analysis"
            className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
            onKeyDown={(e) => e.key === "Enter" && handleSymbolSentiment()}
          />
          <Button
            onClick={handleSymbolSentiment}
            disabled={!symbol.trim() || mutation.isPending}
            className="shrink-0"
            size="sm"
          >
            {mutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Search className="w-4 h-4" />
            )}
          </Button>
        </div>
      </Card>

      {/* Text input */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-4 space-y-3">
        <h4 className="text-sm font-semibold text-text-primary">Paste Text to Analyse</h4>
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste news, social post, or any market commentary here..."
          aria-label="Text to analyse for sentiment"
          rows={4}
          className="bg-surface-base border-border-default text-text-primary text-sm resize-none"
        />
        <div className="flex justify-end">
          <Button
            onClick={handleAnalyze}
            disabled={!text.trim() || mutation.isPending}
            className="gap-2"
            size="sm"
          >
            {mutation.isPending ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Analysing...
              </>
            ) : (
              <>
                <TrendingUp className="w-3.5 h-3.5" />
                Analyse
              </>
            )}
          </Button>
        </div>
      </Card>

      {mutation.isError && (
        <Card className="bg-surface-card border border-bearish-border rounded-lg p-4">
          <div className="flex items-center gap-2 text-loss text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>
              {mutation.error instanceof Error
                ? mutation.error.message
                : "Sentiment analysis failed. Check that the AI backend is running."}
            </span>
          </div>
        </Card>
      )}

      {mutation.isSuccess && mutation.data && (
        <SentimentResultCard result={mutation.data} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Knowledge Base / RAG
// ---------------------------------------------------------------------------

function RAGResultCard({ result, rank }: { result: RAGResult; rank: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionConfig.stagger(rank - 1)}
    >
      <Card className="bg-surface-card border border-border-default rounded-lg p-4 space-y-2">
        <div className="flex items-start justify-between gap-3">
          <span className="text-xs font-mono text-text-muted shrink-0">#{rank}</span>
          <p className="text-xs font-mono text-accent truncate flex-1">{result.source}</p>
          <span className="text-xs text-text-muted font-mono shrink-0">
            {Math.round(result.score * 100)}% match
          </span>
        </div>
        <div className="h-1 bg-surface-base rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-accent rounded-full"
            initial={{ width: "0%" }}
            animate={{ width: `${result.score * 100}%` }}
            transition={{ duration: DURATION.slow, ease: EASE_ENTER, delay: (rank - 1) * 0.05 }}
          />
        </div>
        <p className="text-sm text-text-secondary leading-relaxed line-clamp-4">
          {result.content}
        </p>
      </Card>
    </motion.div>
  );
}

function KnowledgeSection() {
  const [query, setQuery] = useState("");

  const mutation = useMutation({
    mutationFn: (q: string) => queryKnowledge(q, 5),
  });

  function handleQuery() {
    const q = query.trim();
    if (!q) return;
    mutation.mutate(q);
  }

  const results = mutation.data?.results ?? [];
  const answer = mutation.data?.answer ?? "";

  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-5">
        <h3 className="font-heading font-semibold text-base text-text-primary mb-2">
          Knowledge Base (RAG)
        </h3>
        <p className="text-xs text-text-secondary leading-relaxed">
          Query RAG-indexed project docs, order-safety notes, strategy guides, and custom notes.
          Ranked by relevance using ChromaDB vector search.
        </p>
      </Card>

      <Card className="bg-surface-card border border-border-default rounded-lg p-4 space-y-3">
        <div className="flex gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. Iron condor adjustment rules"
            aria-label="Knowledge base query"
            className="bg-surface-base border-border-default text-text-primary text-sm"
            onKeyDown={(e) => e.key === "Enter" && handleQuery()}
          />
          <Button
            onClick={handleQuery}
            disabled={!query.trim() || mutation.isPending}
            className="shrink-0 gap-1.5"
            size="sm"
          >
            {mutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Search className="w-4 h-4" />
            )}
            Query
          </Button>
        </div>
      </Card>

      {mutation.isPending && (
        <div className="flex items-center gap-2 text-text-muted text-sm py-6 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
          Searching knowledge base...
        </div>
      )}

      {mutation.isError && (
        <Card className="bg-surface-card border border-bearish-border rounded-lg p-4">
          <div className="flex items-center gap-2 text-loss text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>
              {mutation.error instanceof Error &&
              mutation.error.message.toLowerCase().includes("rag runtime disabled")
                ? "Knowledge service is disabled. Enable FLINTTRADE_RAG_ENABLED and restart."
                : mutation.error instanceof Error &&
                    /rag engine not available|chroma/i.test(mutation.error.message)
                  ? "Knowledge service unavailable. Install the FlintTrade RAG dependencies and restart."
                : mutation.error instanceof Error
                  ? mutation.error.message
                  : "RAG query failed."}
            </span>
          </div>
        </Card>
      )}

      {mutation.isSuccess && answer && (
        <Card className="bg-surface-card border border-border-default rounded-lg p-4">
          <p className="text-sm text-text-primary leading-relaxed whitespace-pre-wrap">
            {answer}
          </p>
        </Card>
      )}

      {mutation.isSuccess && results.length === 0 && !answer && (
        <Card className="bg-surface-card border border-border-default rounded-lg p-6 text-center">
          <BookOpen className="w-7 h-7 text-text-muted mx-auto mb-2" />
          <p className="text-sm text-text-secondary">No matching documents.</p>
          <p className="text-xs text-text-muted mt-1">
            No indexed document matched this query.
          </p>
        </Card>
      )}

      {mutation.isSuccess && results.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs text-text-muted px-1">
            {results.length} result{results.length !== 1 ? "s" : ""} for &quot;{query}&quot;
          </p>
          {results.map((r, idx) => (
            <RAGResultCard key={`${r.source}-${idx}`} result={r} rank={idx + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: AI Settings (live status)
// ---------------------------------------------------------------------------

async function fetchAdvisorStatus(): Promise<AdvisorStatusData> {
  const base = getBase();
  const resp = await fetch(`${base}/api/v1/advisor/status`);
  if (!resp.ok) throw new Error(`advisor/status: HTTP ${resp.status}`);
  const raw: unknown = await resp.json();
  const result = AdvisorStatusResponseSchema.safeParse(raw);
  if (!result.success) {
    console.error("[AIRoute] /advisor/status shape mismatch:", result.error.issues);
    throw new Error("Advisor status response did not match expected shape");
  }
  if (result.data.status === "error" || !result.data.data) {
    throw new Error("Advisor status unavailable");
  }
  return result.data.data;
}

function AISettingsSection() {
  const authToken = useAuthStore((s) => s.token);
  const hasRealAuthToken = Boolean(authToken && authToken !== "demo-user" && authToken !== "dev-bypass");
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["advisor-status"],
    queryFn: fetchAdvisorStatus,
    enabled: hasRealAuthToken,
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-heading font-semibold text-base text-text-primary">LLM Status</h3>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            disabled={isLoading || !hasRealAuthToken}
            className="text-text-muted hover:text-text-primary gap-1.5 h-7 text-xs"
          >
            <RefreshCw className={`w-3 h-3 ${isLoading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        {!hasRealAuthToken && (
          <div className="flex items-center gap-2 text-text-muted text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            Sign in to check the AI backend status.
          </div>
        )}

        {hasRealAuthToken && isLoading && (
          <div className="flex items-center gap-2 text-text-muted text-sm">
            <Loader2 className="w-4 h-4 animate-spin" />
            Checking advisor...
          </div>
        )}

        {hasRealAuthToken && isError && (
          <div className="flex items-center gap-2 text-loss text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            Could not reach the AI backend. Ensure the FT Python server is running on port 5100.
          </div>
        )}

        {data && (
          <div className="grid grid-cols-1 gap-3">
            <div className="bg-surface-base border border-border-default rounded-lg p-3">
              <p className="text-xs text-text-muted mb-1">Status</p>
              <div className="flex items-center gap-2">
                {data.configured ? (
                  <>
                    <CheckCircle2 className="w-4 h-4 text-profit shrink-0" />
                    <Badge className="bg-bullish-bg text-profit text-xs">Configured</Badge>
                  </>
                ) : (
                  <>
                    <AlertCircle className="w-4 h-4 text-warning shrink-0" />
                    <Badge className="bg-atm-bg text-warning text-xs">Not configured</Badge>
                  </>
                )}
              </div>
            </div>
            <div className="bg-surface-base border border-border-default rounded-lg p-3">
              <p className="text-xs text-text-muted mb-1">Provider</p>
              <p className="text-sm font-mono font-bold text-text-primary">
                {data.provider || "—"}
              </p>
            </div>
            <div className="bg-surface-base border border-border-default rounded-lg p-3">
              <p className="text-xs text-text-muted mb-1">Model</p>
              <p className="text-sm font-mono font-bold text-text-primary truncate">
                {data.model || "—"}
              </p>
            </div>
          </div>
        )}
      </Card>

      <Card className="bg-surface-card border border-border-default rounded-lg p-5">
        <h3 className="font-heading font-semibold text-base text-text-primary mb-3">
          Configuration
        </h3>
        <p className="text-xs text-text-secondary leading-relaxed mb-4">
          Configure the LLM provider, model selection, and AI preferences.
          All settings persist to workspace.json.
        </p>
        <div className="space-y-3">
          {[
            {
              title: "LLM Provider",
              desc: "LM Studio (local), Ollama (local), OpenAI API, Anthropic API, or custom OpenAI-compatible endpoint.",
            },
            {
              title: "Model Selection",
              desc: "Choose from available models. For local: Qwen 3.5, Llama 3, Mistral. Model size affects speed vs quality.",
            },
            {
              title: "API Keys",
              desc: "API keys for cloud providers stored in workspace.json with _ref pattern. Not needed for local LLMs.",
            },
            {
              title: "RAG Settings",
              desc: "ChromaDB collection path, embedding model, chunk size, retrieval top-k. Controls knowledge base indexing.",
            },
          ].map((item) => (
            <div
              key={item.title}
              className="bg-surface-base border border-border-default rounded-lg p-3"
            >
              <h4 className="text-xs font-semibold text-text-primary mb-0.5">{item.title}</h4>
              <p className="text-xs text-text-muted">{item.desc}</p>
            </div>
          ))}
        </div>
      </Card>

      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <Badge className="bg-atm-bg text-warning text-xs">Coming soon</Badge>
        <p className="text-xs text-text-muted mt-2">
          Settings form controls will be available in the next release. Use workspace.json
          directly to configure provider, model, and ChromaDB paths in the meantime.
        </p>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pill navigation — shared route header
// ---------------------------------------------------------------------------

interface FloatingPillNavProps {
  active: SectionId;
  onSelect: (id: SectionId) => void;
  /** Optional filtered list. Defaults to all SECTIONS. */
  sections?: SectionDef[];
}

function FloatingPillNav({ active, onSelect, sections = SECTIONS }: FloatingPillNavProps) {
  const reducedMotion = motionConfig.prefersReducedMotion();

  return (
    <div
      role="navigation"
      aria-label="AI section navigation"
      data-tour-target="ai-section-nav"
      className="min-w-0 max-w-full overflow-x-auto scrollbar-none"
    >
      <div className="inline-flex items-center gap-0.5 bg-glass-chrome backdrop-blur-md border border-glass-l2 rounded-full px-1.5 py-1.5 shadow-lg">
        {sections.map((section) => {
          const Icon = section.icon;
          const isActive = active === section.id;

          return (
            <button
              key={section.id}
              onClick={() => onSelect(section.id)}
              aria-current={isActive ? "true" : undefined}
              aria-label={section.label}
              className="relative flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              style={{ zIndex: 1 }}
            >
              {/* Sliding pill background */}
              {isActive && (
                <motion.span
                  layoutId={reducedMotion ? undefined : "pill-indicator"}
                  className="absolute inset-0 bg-accent rounded-full"
                  style={{ zIndex: -1 }}
                  transition={
                    reducedMotion
                      ? { duration: 0 }
                      : { type: "spring", stiffness: 380, damping: 30 }
                  }
                />
              )}
              <Icon
                className={`w-3.5 h-3.5 shrink-0 transition-colors duration-150 ${
                  isActive ? "text-white" : "text-text-muted"
                }`}
              />
              <span
                className={`transition-colors duration-150 ${
                  isActive ? "text-white" : "text-text-secondary"
                }`}
              >
                {section.label}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overlay panel — slides in from right for non-chat sections
// ---------------------------------------------------------------------------

interface OverlayPanelProps {
  title: string;
  icon: typeof MessageSquare;
  onClose: () => void;
  children: React.ReactNode;
}

function OverlayPanel({ title, icon: Icon, onClose, children }: OverlayPanelProps) {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  // Move focus to close button when panel opens
  useEffect(() => {
    closeButtonRef.current?.focus();
  }, []);

  // Close on Escape
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <motion.div
      role="dialog"
      aria-label={title}
      className="absolute inset-y-0 right-0 w-full max-w-lg z-20 flex flex-col bg-glass-chrome backdrop-blur-md border-l border-glass-l1 shadow-2xl"
      initial={{ x: "100%", opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: "100%", opacity: 0 }}
      transition={{ duration: DURATION.slow, ease: EASE_ENTER }}
    >
      {/* Panel header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-glass-l1 bg-glass-l2 shrink-0">
        <Icon className="w-4 h-4 text-accent" />
        <h2 className="font-heading font-semibold text-sm text-text-primary flex-1">{title}</h2>
        <button
          ref={closeButtonRef}
          type="button"
          onClick={onClose}
          aria-label="Close panel"
          className="h-7 w-7 flex items-center justify-center text-text-muted hover:text-text-primary rounded-full hover:bg-surface-hover transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Panel scrollable content — pb-24 clears the floating pill nav */}
      <ScrollArea className="flex-1">
        <div className="p-5 pb-24 max-w-full">{children}</div>
      </ScrollArea>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Section content map (memoised outside render — no closures on state)
// ---------------------------------------------------------------------------

const SECTION_CONTENT: Record<SectionId, React.ReactNode> = {
  chat: <ChatSection />,
  agent: <AgentPanel />,
  suggestions: <AISuggestionsPanel />,
  signals: <SignalsSection />,
  "market-sentiment": <SentimentPanel />,
  regime: <RegimePanel />,
  sentiment: <SentimentSection />,
  knowledge: <KnowledgeSection />,
  settings: <AISettingsSection />,
};

const SECTION_LABELS: Record<SectionId, string> = {
  chat: "AI Chat",
  agent: "Autonomous Agent",
  suggestions: "AI Strategy Suggestions",
  signals: "Signals",
  "market-sentiment": "Market Sentiment Dashboard",
  regime: "Regime Detector",
  sentiment: "Sentiment Analysis",
  knowledge: "Knowledge Base",
  settings: "AI Settings",
};

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export default function AIRoute() {
  useEffect(() => { useSkillStore.getState().trackAction("ai", "daysActive"); }, []);

  const [searchParams] = useSearchParams();
  const [activeSection, setActiveSection] = useState<SectionId>("chat");
  const [shareCopied, setShareCopied] = useState(false);
  const level = useSkillLevel("ai");

  const loadConversation = useAIConversationStore((s) => s.loadConversation);
  const saveConversation = useAIConversationStore((s) => s.saveConversation);
  const messages = useAIConversationStore((s) => s.messages);

  // Restore shared conversation from ?chat=<id> query param
  useEffect(() => {
    const chatId = searchParams.get("chat");
    if (chatId) {
      loadConversation(chatId);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- run once on mount

  const handleShare = useCallback(() => {
    if (messages.length === 0) return;
    const id = saveConversation();
    const url = new URL(window.location.href);
    url.searchParams.set("chat", id);
    void navigator.clipboard.writeText(url.toString());
    setShareCopied(true);
    setTimeout(() => setShareCopied(false), 2000);
  }, [messages.length, saveConversation]);

  // Density adaptation:
  // Beginner: Chat only — guided prompts, larger focused input
  // Intermediate: Chat + Signals
  // Advanced: All sections (chat, signals, sentiment, knowledge, settings)
  const visibleSectionIds: SectionId[] = useMemo(() => {
    if (level === "beginner") return ["chat", "suggestions"];
    if (level === "intermediate")
      return ["chat", "suggestions", "signals", "market-sentiment", "regime"];
    return [
      "chat",
      "suggestions",
      "signals",
      "market-sentiment",
      "regime",
      "sentiment",
      "knowledge",
      "settings",
    ];
  }, [level]);

  const visibleSections = SECTIONS.filter((s) => visibleSectionIds.includes(s.id));

  const isOverlay = OVERLAY_SECTIONS.has(activeSection);
  const sectionDef = SECTIONS.find((s) => s.id === activeSection);

  function handleSelectSection(id: SectionId) {
    setActiveSection(id);
  }

  function handleCloseOverlay() {
    setActiveSection("chat");
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Top header bar */}
      <div className="border-b border-glass-chrome bg-glass-chrome backdrop-blur-md px-5 py-3 shrink-0">
          <div className="flex flex-wrap items-center gap-3">
            <Bot className="w-5 h-5 text-accent" />
            <div className="flex-1 min-w-[12rem]">
              <h1 className="font-heading font-bold text-sm text-text-primary leading-none">
                AI Center
              </h1>
              <p className="text-xxs text-text-muted mt-0.5">
                {level === "beginner"
                  ? "Ask me anything about markets, stocks, or how to trade"
                  : level === "intermediate"
                    ? "Local LLM advisor · ML signals · Market sentiment · Regime detector"
                  : "Local LLM advisor · ML signals · Market sentiment · Regime · Knowledge base"}
              </p>
            </div>
            {visibleSections.length > 1 && (
              <FloatingPillNav
                active={activeSection}
                onSelect={handleSelectSection}
                sections={visibleSections}
              />
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={handleShare}
              disabled={messages.length === 0}
              className="text-text-muted hover:text-text-primary gap-1.5 h-7 text-xs shrink-0"
              aria-label="Share conversation"
            >
              {shareCopied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-profit" />
                  Copied
                </>
              ) : (
                <>
                  <Share2 className="w-3.5 h-3.5" />
                  Share
                </>
              )}
            </Button>
          </div>
      </div>

      {/* Main content area — relative for overlay positioning */}
      <div className="flex-1 relative overflow-hidden">
        {/* Chat is always rendered underneath (full height) */}
        <div className="absolute inset-0">
          <ChatSection />
        </div>

        {/* Overlay panels slide in from right over the chat */}
        <AnimatePresence>
          {isOverlay && sectionDef && visibleSectionIds.includes(activeSection) && (
            <OverlayPanel
              key={activeSection}
              title={SECTION_LABELS[activeSection]}
              icon={sectionDef.icon}
              onClose={handleCloseOverlay}
            >
              {SECTION_CONTENT[activeSection]}
            </OverlayPanel>
          )}
        </AnimatePresence>
      </div>

      {/* Guided tour — beginner only, first visit */}
      {level === "beginner" && (
        <SpotlightTour
          tourId="ai-beginner"
          steps={TOUR_DEFINITIONS["ai-beginner"] ?? []}
        />
      )}
    </div>
  );
}
