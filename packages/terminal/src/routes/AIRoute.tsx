import { useState } from "react";
import {
  Bot,
  MessageSquare,
  Zap,
  TrendingUp,
  BookOpen,
  Settings2,
  ChevronRight,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";

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
// Section content components
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

function SignalsSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          ML-Powered Signals
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Machine learning models analyze price action, volume, open interest, and technical
          indicators to generate buy/sell signals. Models are trained on Indian market data
          using LightGBM for fast inference.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Signal Types</h4>
            <ul className="text-xs text-text-secondary space-y-1">
              <li>Trend direction (bullish/bearish/neutral)</li>
              <li>Entry/exit timing</li>
              <li>Volatility regime classification</li>
              <li>Support/resistance breakout probability</li>
            </ul>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Input Features</h4>
            <ul className="text-xs text-text-secondary space-y-1">
              <li>Price action (OHLCV)</li>
              <li>Technical indicators (RSI, MACD, BB, etc.)</li>
              <li>Open interest changes</li>
              <li>Volume profile</li>
            </ul>
          </div>
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <Badge className="bg-amber-500/20 text-amber-400 text-xs">Coming in v0.2.0</Badge>
        <p className="text-sm text-text-muted mt-2">
          Signal pipeline will be connected to the Python AI package in the next release.
          LightGBM models are being trained on Indian F&O data.
        </p>
      </Card>
    </div>
  );
}

function SentimentSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Sentiment Analysis
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Real-time sentiment analysis of financial news, social media, and market commentary.
          Understand market mood before making trading decisions. Sentiment scores are computed
          locally using the LLM for privacy.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">News Sources</h4>
            <ul className="text-xs text-text-secondary space-y-1">
              <li>Moneycontrol</li>
              <li>Economic Times</li>
              <li>LiveMint</li>
              <li>Reuters India</li>
            </ul>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Social Sources</h4>
            <ul className="text-xs text-text-secondary space-y-1">
              <li>Twitter/X (cashtags)</li>
              <li>Reddit (r/IndianStreetBets)</li>
              <li>Trading forums</li>
              <li>Broker research</li>
            </ul>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Output</h4>
            <ul className="text-xs text-text-secondary space-y-1">
              <li>Sentiment score (-1 to +1)</li>
              <li>Bullish/Bearish label</li>
              <li>Key topics extracted</li>
              <li>Confidence level</li>
            </ul>
          </div>
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <Badge className="bg-amber-500/20 text-amber-400 text-xs">Coming in v0.2.0</Badge>
        <p className="text-sm text-text-muted mt-2">
          Sentiment feeds will be connected to the Python AI package in the next release.
        </p>
      </Card>
    </div>
  );
}

function KnowledgeSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Knowledge Base (RAG)
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          A retrieval-augmented generation (RAG) system indexed with trading documentation,
          strategy guides, SEBI regulations, and your own notes. The AI advisor uses this
          knowledge base to provide accurate, contextual answers powered by ChromaDB.
        </p>
        <div className="bg-surface-base border border-border-default rounded-lg p-4">
          <h4 className="text-sm font-semibold text-text-primary mb-2">Indexed Sources</h4>
          <ul className="space-y-1.5 text-sm text-text-secondary">
            <li className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
              SEBI regulations and circulars
            </li>
            <li className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
              Options strategy playbook (12 strategies)
            </li>
            <li className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
              Technical analysis reference
            </li>
            <li className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
              OpenAlgo API documentation
            </li>
            <li className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
              Your custom notes and research (user-added)
            </li>
          </ul>
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <Badge className="bg-amber-500/20 text-amber-400 text-xs">Coming in v0.2.0</Badge>
        <p className="text-sm text-text-muted mt-2">
          Knowledge base management UI will be available in the next release. ChromaDB
          indexing is already supported by the Python AI package.
        </p>
      </Card>
    </div>
  );
}

function AISettingsSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
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
          Settings will be persisted to workspace.json and configurable via form controls.
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
                <ChevronRight className={`w-3 h-3 ml-auto ${isActive ? "opacity-100" : "opacity-0"}`} />
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
