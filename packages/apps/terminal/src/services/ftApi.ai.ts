import { get, post } from "./ftApi.helpers";

export interface Signal {
  symbol: string;
  exchange: string;
  signal_type: "BUY" | "SELL" | "HOLD";
  confidence: number;
  timestamp: string;
  indicators: Record<string, number>;
}

export interface LiveSignal {
  timestamp: string;
  symbol: string;
  signal_type: "BUY" | "SELL" | "ALERT";
  indicator: string;
  value: number;
  threshold: number;
  confidence: number;
  message: string;
}

export interface SignalConfig {
  instruments: string[];
  indicators: Array<{ name: string; params: Record<string, number> }>;
  thresholds: Record<string, number>;
}

export interface SentimentResult {
  score: number;
  label: "bullish" | "bearish" | "neutral";
  confidence: number;
}

export interface RAGResult {
  content: string;
  source: string;
  score: number;
}

export interface AgentRoleConfig {
  name: string;
  role_type:
    | "technical"
    | "fundamental"
    | "sentiment"
    | "risk_manager"
    | "aggregator";
  system_prompt: string;
  enabled: boolean;
  temperature: number | null;
}

export interface AgentAnalysisResult {
  agent_name: string;
  role_type: string;
  report: string;
  signal: "BUY" | "SELL" | "HOLD";
  confidence: number;
  timestamp: string;
  error: string;
}

export interface TeamAnalysisResult {
  symbol: string;
  exchange: string;
  agent_analyses: AgentAnalysisResult[];
  consensus_signal: "BUY" | "SELL" | "HOLD";
  consensus_confidence: number;
  consensus_reasoning: string;
  timestamp: string;
  errors: string[];
}

export interface TeamRecommendation {
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: number;
  reasoning: string;
  agent_count: number;
  bullish_count: number;
  bearish_count: number;
  neutral_count: number;
  timestamp: string;
}

export interface TeamAnalyzeResponse {
  analysis: TeamAnalysisResult;
  recommendation: TeamRecommendation;
}

export interface TeamConfig {
  agents: AgentRoleConfig[];
}

export interface OpenClawStatusData {
  connected: boolean;
}

export interface OpenClawAgentData {
  id: string;
  name: string;
  status: string;
  strategy: string;
  symbols: string[];
  created_at: string;
}

export interface VoiceCommandResult {
  intent: string;
  action: "BUY" | "SELL" | null;
  symbol: string | null;
  exchange: string | null;
  quantity: number | null;
  price_type: "MARKET" | "LIMIT" | null;
  price: number | null;
  product: string;
  confidence: number;
  raw_text: string;
  error: string;
  is_valid: boolean;
}

export const getActiveSignals = () => get<{ signals: Signal[] }>("signals/active");

export const getRecentSignals = (limit?: number) => {
  const qs = limit !== undefined ? `?limit=${limit}` : "";
  return get<{ signals: LiveSignal[] }>("signals/recent" + qs);
};

export const getSignalConfig = () => get<SignalConfig>("signals/config");

export const updateSignalConfig = (config: Partial<SignalConfig>) =>
  post<SignalConfig>("signals/configure", config);

export const analyzeSentiment = (text: string) =>
  post<SentimentResult>("sentiment/analyse", { text });

export const queryKnowledge = (query: string, top_k?: number) =>
  post<{ results: RAGResult[] }>("rag/query", {
    query,
    top_k: top_k ?? 5,
  });

export const runTeamAnalysis = (
  symbol: string,
  exchange: string,
  market_data?: Record<string, unknown>,
) =>
  post<TeamAnalyzeResponse>("ai/team/analyse", {
    symbol,
    exchange,
    ...(market_data ? { market_data: market_data } : {}),
  });

export const getTeamConfig = () => get<TeamConfig>("ai/team/config");

export const updateTeamConfig = (config: TeamConfig) =>
  post<TeamConfig>("ai/team/config", config);

export const getOpenClawStatus = () =>
  get<OpenClawStatusData>("ai/openclaw/status");

export const getOpenClawAgents = () =>
  get<{ agents: OpenClawAgentData[] }>("ai/openclaw/agents");

export interface OpenClawDeployConfig {
  name: string;
  strategy: string;
  symbols: string[];
}

export const deployOpenClawAgent = (config: OpenClawDeployConfig) =>
  post<{ agent_id?: string; status?: string }>("ai/openclaw/agents", config);

export const stopOpenClawAgent = (agentId: string) =>
  post<Record<string, unknown>>(
    `ai/openclaw/agents/${encodeURIComponent(agentId)}/stop`,
    {},
  );

export const getOpenClawAgentLogs = (agentId: string) =>
  get<{ logs: string[] }>(
    `ai/openclaw/agents/${encodeURIComponent(agentId)}/logs`,
  );

export const parseVoiceCommand = (text: string): Promise<VoiceCommandResult> =>
  post<VoiceCommandResult>("voice/parse", { text });

// ---------------------------------------------------------------------------
// Market Sentiment Dashboard (structured_sentiment.py — MarketSummary schema)
// ---------------------------------------------------------------------------

export type SentimentLabel =
  | "STRONGLY_BULLISH"
  | "BULLISH"
  | "NEUTRAL"
  | "BEARISH"
  | "STRONGLY_BEARISH";

export type IndexSignal = "BUY" | "SELL" | "HOLD" | "WATCH";

export interface IndexSnapshot {
  name: string;
  value: number;
  change_pct: number;
  signal: IndexSignal;
}

export interface SectorOutlook {
  name: string;
  /** "Outperforming" | "Underperforming" | "Neutral" */
  performance: string;
  outlook: string;
}

export interface FiiDiiFlow {
  fii_net: number;
  dii_net: number;
  interpretation: string;
}

export interface MarketSummary {
  sentiment_score: number;
  market_sentiment: SentimentLabel;
  indices: IndexSnapshot[];
  sectors: SectorOutlook[];
  key_points: string[];
  fii_dii_flow: FiiDiiFlow;
  risks: string[];
  opportunities: string[];
}

export const getMarketSentimentSummary = () =>
  get<MarketSummary>("ai/sentiment/summary");

// ---------------------------------------------------------------------------
// Regime Detector (regime_detector.py — RegimeResult)
// ---------------------------------------------------------------------------

export type RegimeState =
  | "TRENDING_UP"
  | "TRENDING_DOWN"
  | "RANGING"
  | "VOLATILE_DIRECTIONAL"
  | "VOLATILE_DIRECTIONLESS"
  | "LOW_VOLATILITY";

/** A regime-appropriate strategy recommendation (closes the loop on detection). */
export interface RegimeStrategySuggestion {
  strategy: string;
  label: string;
  rationale: string;
}

export interface RegimeResult {
  state: RegimeState;
  adx: number;
  bb_width: number;
  atr_current: number;
  atr_slope: number;
  plus_di: number;
  minus_di: number;
  close: number;
  n_bars: number;
  /** Backend-recommended strategy style for the detected regime. */
  suggested_strategy?: RegimeStrategySuggestion;
}

export const getRegimeDetector = (symbol: string) =>
  get<RegimeResult>(`ai/regime?symbol=${encodeURIComponent(symbol)}`);

// ---------------------------------------------------------------------------
// Per-ticker Sentiment Table (visual_sentiment.py or LLM-derived)
// ---------------------------------------------------------------------------

export interface TickerSentiment {
  ticker: string;
  score: number; // -10 to +10
  label: "positive" | "negative" | "neutral";
  key_factor: string;
}

export const getTickerSentiments = () =>
  get<{ tickers: TickerSentiment[] }>("ai/sentiment/tickers");

// ---------------------------------------------------------------------------
// Overnight optimiser reports (overnight_optimiser.py -> OptimiserReportStore)
// ---------------------------------------------------------------------------

export interface OptimiserSuggestion {
  strategy_name: string;
  analysis: string;
  suggested_params: Record<string, unknown>;
  reasoning: string;
  confidence: number;
  timestamp?: string;
}

export interface OptimiserReport {
  timestamp: string;
  strategies_seen: number;
  strategies_optimised: number;
  suggestions: OptimiserSuggestion[];
  errors: Array<{ strategy: string; error: string }>;
}

/** The most recent overnight optimisation report, or null when none exist yet. */
export const getLatestOptimiserReport = () =>
  get<{ report: OptimiserReport | null }>("ai/optimiser/reports/latest");

// ---------------------------------------------------------------------------
// Obsidian vault (obsidian_routes.py -> ObsidianVault). Read-only browsing.
// All routes return an honest 503 when FLINTTRADE_OBSIDIAN_VAULT is unset.
// ---------------------------------------------------------------------------

export interface ObsidianStatus {
  configured: boolean;
  available: boolean;
  vault_path: string | null;
}

export interface ObsidianSearchHit {
  path: string;
  snippet: string;
}

/** Vault configuration + availability (never 503 — reports configured=false). */
export const getObsidianStatus = () =>
  get<ObsidianStatus>("ai/obsidian/status");

/** Every note's vault-relative path (sorted). */
export const listObsidianNotes = () =>
  get<string[]>("ai/obsidian/notes");

/** Read a single note's markdown by its vault-relative path. */
export const readObsidianNote = (path: string) =>
  get<{ path: string; content: string }>(
    "ai/obsidian/note?path=" + encodeURIComponent(path),
  );

/** Case-insensitive search across note names and bodies. */
export const searchObsidianNotes = (query: string) =>
  get<ObsidianSearchHit[]>("ai/obsidian/search?q=" + encodeURIComponent(query));
