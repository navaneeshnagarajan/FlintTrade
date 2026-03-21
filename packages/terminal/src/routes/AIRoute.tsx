import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  Bot,
  MessageSquare,
  Zap,
  TrendingUp,
  BookOpen,
  Settings2,
  ChevronRight,
  RefreshCw,
  Search,
  AlertCircle,
  Loader2,
  CheckCircle2,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  getActiveSignals,
  analyzeSentiment,
  queryKnowledge,
  type Signal,
  type SentimentResult,
  type RAGResult,
} from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Section registry
// ---------------------------------------------------------------------------

type SectionId = "chat" | "signals" | "sentiment" | "knowledge" | "settings";

interface SectionDef {
  id: SectionId;
  label: string;
  icon: typeof MessageSquare;
  desc: string;
}

const SECTIONS: SectionDef[] = [
  { id: "chat", label: "AI Chat", icon: MessageSquare, desc: "Conversational AI trading advisor" },
  { id: "signals", label: "Signals", icon: Zap, desc: "ML-powered buy/sell signals" },
  { id: "sentiment", label: "Sentiment", icon: TrendingUp, desc: "News sentiment analysis" },
  { id: "knowledge", label: "Knowledge Base", icon: BookOpen, desc: "RAG-indexed trading docs" },
  { id: "settings", label: "AI Settings", icon: Settings2, desc: "LLM provider, model, API keys" },
];

// ---------------------------------------------------------------------------
// Section: Chat (already wired — display only)
// ---------------------------------------------------------------------------

function ChatSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          AI Trading Advisor
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Chat with a local LLM-powered trading advisor that understands your portfolio,
          open positions, and market context. Ask about strategy ideas, risk analysis,
          trade setups, and market conditions — all processed locally for privacy.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <p className="text-xs text-text-muted mb-1">Processing</p>
            <p className="text-lg font-mono font-bold text-accent">Local LLM</p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <p className="text-xs text-text-muted mb-1">Context</p>
            <p className="text-lg font-mono font-bold text-text-primary">Portfolio-aware</p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <p className="text-xs text-text-muted mb-1">Privacy</p>
            <p className="text-lg font-mono font-bold text-text-primary">100% Local</p>
          </div>
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-sm text-text-primary mb-2">
          Example Questions
        </h3>
        <ul className="space-y-2 text-sm text-text-secondary">
          {[
            "What is the risk/reward of selling a NIFTY straddle at current IV?",
            "Analyze my open positions — should I hedge?",
            "Suggest a strategy for tomorrow based on OI data",
            "Explain the Greeks of my current options portfolio",
            "What happened to BANKNIFTY in the last 30 minutes?",
          ].map((q) => (
            <li key={q} className="flex items-start gap-2">
              <MessageSquare className="w-3.5 h-3.5 text-accent shrink-0 mt-0.5" />
              <span>{q}</span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Signals
// ---------------------------------------------------------------------------

function signalBadgeClass(type: Signal["signal_type"]): string {
  if (type === "BUY") return "bg-green-500/20 text-green-400";
  if (type === "SELL") return "bg-red-500/20 text-red-400";
  return "bg-surface-base text-text-muted";
}

function SignalCard({ signal }: { signal: Signal }) {
  const indicatorEntries = Object.entries(signal.indicators);
  return (
    <Card className="bg-surface-card border border-border-default rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <span className="font-mono font-bold text-text-primary text-sm">{signal.symbol}</span>
          <span className="ml-2 text-xs text-text-muted">{signal.exchange}</span>
        </div>
        <Badge className={`text-xs font-semibold ${signalBadgeClass(signal.signal_type)}`}>
          {signal.signal_type}
        </Badge>
      </div>

      {/* Confidence bar */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs text-text-muted">
          <span>Confidence</span>
          <span className="font-mono">{Math.round(signal.confidence * 100)}%</span>
        </div>
        <div className="h-1.5 bg-surface-base rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              signal.signal_type === "BUY"
                ? "bg-green-500"
                : signal.signal_type === "SELL"
                  ? "bg-red-500"
                  : "bg-text-muted"
            }`}
            style={{ width: `${signal.confidence * 100}%` }}
          />
        </div>
      </div>

      {/* Indicator values */}
      {indicatorEntries.length > 0 && (
        <div className="flex flex-wrap gap-2">
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
  );
}

function SignalsSection() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["signals"],
    queryFn: getActiveSignals,
    refetchInterval: 30_000,
  });

  const signals = data?.signals ?? [];

  return (
    <div className="space-y-4">
      {/* Header card */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-heading font-semibold text-lg text-text-primary">
            ML-Powered Signals
          </h3>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            disabled={isLoading}
            className="text-text-muted hover:text-text-primary gap-1.5"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
        <p className="text-sm text-text-secondary leading-relaxed">
          Machine learning models analyze price action, volume, open interest, and technical
          indicators to generate buy/sell signals. Models are trained on Indian market data
          using LightGBM for fast inference. Auto-refreshes every 30s.
        </p>
      </Card>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center gap-2 text-text-muted text-sm py-4 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
          Fetching signals...
        </div>
      )}

      {/* Error */}
      {isError && (
        <Card className="bg-surface-card border border-red-500/30 rounded-lg p-4">
          <div className="flex items-center gap-2 text-red-400 text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>Signal service unavailable.</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            className="mt-3 text-text-muted hover:text-text-primary"
          >
            Retry
          </Button>
        </Card>
      )}

      {/* Empty */}
      {!isLoading && !isError && signals.length === 0 && (
        <Card className="bg-surface-card border border-border-default rounded-lg p-6 text-center">
          <Zap className="w-8 h-8 text-text-muted mx-auto mb-3" />
          <p className="text-sm text-text-secondary">No active signals.</p>
          <p className="text-xs text-text-muted mt-1">
            The signal pipeline generates signals during market hours.
          </p>
        </Card>
      )}

      {/* Signal cards */}
      {!isLoading && !isError && signals.length > 0 && (
        <div className="space-y-3">
          {signals.map((signal, idx) => (
            <SignalCard key={`${signal.symbol}-${signal.timestamp}-${idx}`} signal={signal} />
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
  if (score > 0.1) return "text-green-400";
  if (score < -0.1) return "text-red-400";
  return "text-amber-400";
}

function labelBadgeClass(label: SentimentResult["label"]): string {
  if (label === "bullish") return "bg-green-500/20 text-green-400";
  if (label === "bearish") return "bg-red-500/20 text-red-400";
  return "bg-amber-500/20 text-amber-400";
}

function SentimentResult({ result }: { result: SentimentResult }) {
  const pct = Math.round(Math.abs(result.score) * 100);
  const gaugeWidth = Math.round(((result.score + 1) / 2) * 100);

  return (
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
          {/* Centre tick */}
          <div className="absolute left-1/2 top-0 w-px h-full bg-border-default" />
          <div
            className={`absolute top-0 h-full rounded-full transition-all ${
              result.score > 0.1
                ? "bg-green-500"
                : result.score < -0.1
                  ? "bg-red-500"
                  : "bg-amber-500"
            }`}
            style={{ left: "50%", width: `${pct / 2}%`, transform: result.score < 0 ? "translateX(-100%)" : undefined }}
          />
        </div>
        {/* Pointer */}
        <div
          className="relative h-0"
          style={{ marginLeft: `${gaugeWidth}%`, transform: "translateX(-50%)" }}
        >
          <div
            className={`text-xs font-mono font-bold leading-none ${scoreToColor(result.score)}`}
          >
            ▲
          </div>
        </div>
      </div>
    </Card>
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
      {/* Header */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Sentiment Analysis
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed">
          Paste news headlines, social posts, or any financial text to analyze its market
          sentiment. Score ranges from -1 (strongly bearish) to +1 (strongly bullish).
          Computed locally via the LLM for full privacy.
        </p>
      </Card>

      {/* Quick symbol lookup */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-5 space-y-3">
        <h4 className="text-sm font-semibold text-text-primary">Quick Symbol Sentiment</h4>
        <div className="flex gap-2">
          <Input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="e.g. NIFTY, RELIANCE"
            className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
            onKeyDown={(e) => e.key === "Enter" && handleSymbolSentiment()}
          />
          <Button
            onClick={handleSymbolSentiment}
            disabled={!symbol.trim() || mutation.isPending}
            className="shrink-0"
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
      <Card className="bg-surface-card border border-border-default rounded-lg p-5 space-y-3">
        <h4 className="text-sm font-semibold text-text-primary">Paste Text to Analyze</h4>
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste news, social post, or any market commentary here..."
          rows={5}
          className="bg-surface-base border-border-default text-text-primary text-sm resize-none"
        />
        <div className="flex justify-end">
          <Button
            onClick={handleAnalyze}
            disabled={!text.trim() || mutation.isPending}
            className="gap-2"
          >
            {mutation.isPending ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Analyzing...
              </>
            ) : (
              <>
                <TrendingUp className="w-4 h-4" />
                Analyze
              </>
            )}
          </Button>
        </div>
      </Card>

      {/* Error */}
      {mutation.isError && (
        <Card className="bg-surface-card border border-red-500/30 rounded-lg p-4">
          <div className="flex items-center gap-2 text-red-400 text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>
              {mutation.error instanceof Error
                ? mutation.error.message
                : "Sentiment analysis failed. Check that the AI backend is running."}
            </span>
          </div>
        </Card>
      )}

      {/* Result */}
      {mutation.isSuccess && mutation.data && (
        <SentimentResult result={mutation.data} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Knowledge Base / RAG
// ---------------------------------------------------------------------------

function RAGResultCard({ result, rank }: { result: RAGResult; rank: number }) {
  return (
    <Card className="bg-surface-card border border-border-default rounded-lg p-4 space-y-2">
      <div className="flex items-start justify-between gap-3">
        <span className="text-xs font-mono text-text-muted shrink-0">#{rank}</span>
        <p className="text-xs font-mono text-accent truncate flex-1">{result.source}</p>
        <span className="text-xs text-text-muted font-mono shrink-0">
          {Math.round(result.score * 100)}% match
        </span>
      </div>

      {/* Relevance bar */}
      <div className="h-1 bg-surface-base rounded-full overflow-hidden">
        <div
          className="h-full bg-accent rounded-full"
          style={{ width: `${result.score * 100}%` }}
        />
      </div>

      <p className="text-sm text-text-secondary leading-relaxed line-clamp-4">
        {result.content}
      </p>
    </Card>
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

  return (
    <div className="space-y-4">
      {/* Header */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Knowledge Base (RAG)
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed">
          Query your RAG-indexed trading documentation, SEBI regulations, strategy guides,
          and custom notes. Results are ranked by relevance using ChromaDB vector search.
        </p>
      </Card>

      {/* Search */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-5 space-y-3">
        <div className="flex gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. Iron condor adjustment rules"
            className="bg-surface-base border-border-default text-text-primary text-sm"
            onKeyDown={(e) => e.key === "Enter" && handleQuery()}
          />
          <Button
            onClick={handleQuery}
            disabled={!query.trim() || mutation.isPending}
            className="shrink-0 gap-1.5"
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

      {/* Loading */}
      {mutation.isPending && (
        <div className="flex items-center gap-2 text-text-muted text-sm py-4 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
          Searching knowledge base...
        </div>
      )}

      {/* Error */}
      {mutation.isError && (
        <Card className="bg-surface-card border border-red-500/30 rounded-lg p-4">
          <div className="flex items-center gap-2 text-red-400 text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>
              {mutation.error instanceof Error &&
              mutation.error.message.toLowerCase().includes("chroma")
                ? "RAG engine not configured — install chromadb and configure in Settings."
                : mutation.error instanceof Error
                  ? mutation.error.message
                  : "RAG query failed."}
            </span>
          </div>
        </Card>
      )}

      {/* Empty after query */}
      {mutation.isSuccess && results.length === 0 && (
        <Card className="bg-surface-card border border-border-default rounded-lg p-6 text-center">
          <BookOpen className="w-8 h-8 text-text-muted mx-auto mb-3" />
          <p className="text-sm text-text-secondary">No results found.</p>
          <p className="text-xs text-text-muted mt-1">
            Knowledge base not indexed. Index your docs in AI Settings.
          </p>
        </Card>
      )}

      {/* Results */}
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

interface AdvisorStatusData {
  configured: boolean;
  provider: string;
  model: string;
}

interface AdvisorStatusResponse {
  status: "success" | "error";
  data?: AdvisorStatusData;
}

async function fetchAdvisorStatus(): Promise<AdvisorStatusData> {
  const base = import.meta.env.DEV ? "/ft-api" : "";
  const resp = await fetch(`${base}/api/v1/advisor/status`);
  if (!resp.ok) throw new Error(`advisor/status: HTTP ${resp.status}`);
  const json = (await resp.json()) as AdvisorStatusResponse;
  if (json.status === "error" || !json.data) {
    throw new Error("Advisor status unavailable");
  }
  return json.data;
}

function AISettingsSection() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["advisor-status"],
    queryFn: fetchAdvisorStatus,
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-4">
      {/* Live LLM status */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-heading font-semibold text-lg text-text-primary">
            LLM Status
          </h3>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            disabled={isLoading}
            className="text-text-muted hover:text-text-primary gap-1.5"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        {isLoading && (
          <div className="flex items-center gap-2 text-text-muted text-sm">
            <Loader2 className="w-4 h-4 animate-spin" />
            Checking advisor...
          </div>
        )}

        {isError && (
          <div className="flex items-center gap-2 text-red-400 text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            Could not reach the AI backend. Ensure the FT Python server is running on port 5001.
          </div>
        )}

        {data && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="bg-surface-base border border-border-default rounded-lg p-4">
              <p className="text-xs text-text-muted mb-1">Status</p>
              <div className="flex items-center gap-2">
                {data.configured ? (
                  <>
                    <CheckCircle2 className="w-4 h-4 text-green-400 shrink-0" />
                    <Badge className="bg-green-500/20 text-green-400 text-xs">Configured</Badge>
                  </>
                ) : (
                  <>
                    <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
                    <Badge className="bg-amber-500/20 text-amber-400 text-xs">Not configured</Badge>
                  </>
                )}
              </div>
            </div>
            <div className="bg-surface-base border border-border-default rounded-lg p-4">
              <p className="text-xs text-text-muted mb-1">Provider</p>
              <p className="text-sm font-mono font-bold text-text-primary">
                {data.provider || "—"}
              </p>
            </div>
            <div className="bg-surface-base border border-border-default rounded-lg p-4">
              <p className="text-xs text-text-muted mb-1">Model</p>
              <p className="text-sm font-mono font-bold text-text-primary truncate">
                {data.model || "—"}
              </p>
            </div>
          </div>
        )}
      </Card>

      {/* Static config reference cards */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-4">
          AI Settings
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Configure the LLM provider, model selection, and AI feature preferences.
          All settings are persisted to workspace.json.
        </p>
        <div className="space-y-4">
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">LLM Provider</h4>
            <p className="text-xs text-text-muted">
              LM Studio (local), Ollama (local), OpenAI API, Anthropic API, or custom
              OpenAI-compatible endpoint. Local providers are recommended for privacy.
            </p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Model Selection</h4>
            <p className="text-xs text-text-muted">
              Choose from available models on your provider. For local: Qwen 3.5, Llama 3,
              Mistral. Model size affects speed vs quality tradeoff.
            </p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">API Keys</h4>
            <p className="text-xs text-text-muted">
              API keys for cloud providers (stored in workspace.json with _ref pattern).
              Not needed for local LLM providers.
            </p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">RAG Settings</h4>
            <p className="text-xs text-text-muted">
              ChromaDB collection path, embedding model, chunk size, retrieval top-k.
              Controls how the knowledge base is indexed and queried.
            </p>
          </div>
        </div>
      </Card>

      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <Badge className="bg-amber-500/20 text-amber-400 text-xs">Coming in v0.2.0</Badge>
        <p className="text-sm text-text-muted mt-2">
          Settings form controls will be available in the next release. Use workspace.json
          directly to configure provider, model, and ChromaDB paths in the meantime.
        </p>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export default function AIRoute() {
  const [activeSection, setActiveSection] = useState<SectionId>("chat");

  const sectionContent: Record<SectionId, React.ReactNode> = {
    chat: <ChatSection />,
    signals: <SignalsSection />,
    sentiment: <SentimentSection />,
    knowledge: <KnowledgeSection />,
    settings: <AISettingsSection />,
  };

  return (
    <div className="h-full bg-surface-base flex flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-border-default bg-surface-card px-6 py-4">
        <div className="flex items-center gap-3">
          <Bot className="w-6 h-6 text-accent" />
          <div>
            <h1 className="font-heading font-bold text-lg text-text-primary">AI Center</h1>
            <p className="text-xxs text-text-muted">
              Local LLM advisor, ML signals, sentiment analysis — your AI trading companion
            </p>
          </div>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <div className="w-56 border-r border-border-default bg-surface-card shrink-0 py-2">
          {SECTIONS.map((section) => {
            const Icon = section.icon;
            const isActive = activeSection === section.id;
            return (
              <button
                key={section.id}
                onClick={() => setActiveSection(section.id)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm font-sans transition-colors ${
                  isActive
                    ? "text-accent bg-accent/10 border-l-2 border-accent"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface-base"
                }`}
              >
                <Icon className="w-4 h-4" />
                {section.label}
                <ChevronRight
                  className={`w-3 h-3 ml-auto ${isActive ? "opacity-100" : "opacity-0"}`}
                />
              </button>
            );
          })}
        </div>

        {/* Content */}
        <ScrollArea className="flex-1">
          <div className="p-6 max-w-4xl">{sectionContent[activeSection]}</div>
        </ScrollArea>
      </div>
    </div>
  );
}
