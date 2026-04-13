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
  post<SentimentResult>("sentiment/analyze", { text });

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
  post<TeamAnalyzeResponse>("ai/team/analyze", {
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

export const parseVoiceCommand = (text: string): Promise<VoiceCommandResult> =>
  post<VoiceCommandResult>("voice/parse", { text });
