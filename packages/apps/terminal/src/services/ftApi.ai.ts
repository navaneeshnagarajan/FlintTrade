import { buildHeaders, get, getBase, post } from "./ftApi.helpers";
import { z } from "zod";
import { assertNativeWriteTargetReadyOrThrow, pickNativeBrokerOrderTarget } from "@/services/brokerTargets";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";

export interface SignalIdentityFields {
  event_id: number;
  /** Backend process identity; qualifies event_id across service restarts. */
  stream_id?: string;
  symbol: string;
  exchange: string;
  timestamp: string;
  source: "rule" | "ml" | "fallback";
  method: string;
}

export interface SignalCardModel extends SignalIdentityFields {
  signal_type: "BUY" | "SELL" | "HOLD";
  confidence: number;
  indicators: Record<string, number>;
  message: string;
}

export type Signal = SignalCardModel;

export interface SignalEvent extends SignalIdentityFields {
  signal_type: "BUY" | "SELL" | "HOLD" | "ALERT";
  indicator: string;
  value: number;
  threshold: number;
  confidence: number;
  message: string;
  metadata: Record<string, unknown>;
}

/** Stable event identity shared by reconciliation and React list rendering. */
export function getSignalIdentity(signal: SignalIdentityFields): string {
  if (signal.event_id > 0 && signal.stream_id) {
    return `${signal.stream_id}:${signal.event_id}`;
  }
  const legacyFields = [
    signal.event_id,
    signal.timestamp,
    signal.source,
    signal.exchange,
    signal.symbol,
    signal.method,
  ].map((field) => encodeURIComponent(String(field)));
  return `legacy:${legacyFields.join(":")}`;
}

const signalEventPayloadSchema = z.object({
  event_id: z.number().int().nonnegative().default(0),
  stream_id: z.string().trim().min(1).max(256).optional(),
  timestamp: z.string(),
  symbol: z.string(),
  exchange: z.string().default(""),
  signal_type: z.enum(["BUY", "SELL", "HOLD", "ALERT"]),
  source: z.enum(["rule", "ml", "fallback"]).default("rule"),
  method: z.string().default(""),
  indicator: z.string(),
  value: z.number(),
  threshold: z.number(),
  confidence: z.number(),
  message: z.string(),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

export const signalEventSchema = signalEventPayloadSchema.transform((event): SignalEvent => {
  if (event.method.startsWith("ema_crossover_fallback")) {
    return { ...event, source: "fallback" };
  }
  if (event.method.startsWith("ml_model")) {
    return { ...event, source: "ml" };
  }
  return event;
});

const recentSignalsSchema = z.object({
  stream_id: z.string().trim().min(1).max(256).optional(),
  signals: z.array(signalEventSchema),
}).transform(({ stream_id, signals }) => ({
  signals: stream_id
    ? signals.map((signal) => ({ ...signal, stream_id }))
    : signals,
}));

export type LiveSignal = SignalEvent;

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

export interface RAGQueryResponse {
  answer?: string;
  results: RAGResult[];
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
  role_id?: string;
  model_tier?: "quick" | "deep";
}

export type TeamMode = "flat" | "dag" | "sequential" | "debate";

export interface TeamPresetAgent {
  role: string;
  system_prompt: string;
  model_tier: "quick" | "deep";
}

export interface TeamPreset {
  name: string;
  description: string;
  agents: TeamPresetAgent[];
}

export interface AgentAnalysisResult {
  agent_name: string;
  role_type: string;
  report: string;
  signal: "BUY" | "SELL" | "HOLD";
  confidence: number;
  timestamp: string;
  error: string;
  task_id?: string;
  model_tier?: "quick" | "deep";
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
  mode?: TeamMode;
  preset?: string;
  details?: Record<string, unknown>;
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
  custom_agents?: AgentRoleConfig[];
  modes?: TeamMode[];
  presets?: TeamPreset[];
  active_preset?: string;
}

export type TeamConfigUpdate = { agents: AgentRoleConfig[] } | { preset: string };

export interface TeamRunOptions {
  mode?: TeamMode;
  preset?: string | null;
  debate_rounds?: number;
  max_concurrent?: number;
  task_timeout_seconds?: number;
}

export interface TeamLifecycleEvent {
  task_id: string;
  agent_role: string;
  event_type: "started" | "progress" | "completed" | "error" | "timeout";
  data: Record<string, unknown>;
  timestamp: string;
}

export type TeamStreamFrame =
  | { type: "event"; event: TeamLifecycleEvent }
  | { type: "result"; data: TeamAnalyzeResponse }
  | { type: "error"; message: string }
  | { type: "done" };

export const getRecentSignals = async (limit?: number) => {
  const qs = limit !== undefined ? `?limit=${limit}` : "";
  const payload = await get<unknown>("signals/recent" + qs);
  return recentSignalsSchema.parse(payload);
};

export const getSignalConfig = () => get<SignalConfig>("signals/config");

export const updateSignalConfig = (config: Partial<SignalConfig>) =>
  post<SignalConfig>("signals/configure", config);

export const analyzeSentiment = (text: string) =>
  post<SentimentResult>("sentiment/analyse", { text });

export const queryKnowledge = (query: string, top_k?: number) =>
  post<RAGQueryResponse>("rag/query", {
    query,
    top_k: top_k ?? 5,
  });

export const runTeamAnalysis = (
  symbol: string,
  exchange: string,
  market_data?: Record<string, unknown>,
  options: TeamRunOptions = {},
) =>
  post<TeamAnalyzeResponse>("ai/team/analyse", {
    symbol,
    exchange,
    ...(market_data ? { market_data: market_data } : {}),
    ...options,
  });

export const getTeamConfig = () => get<TeamConfig>("ai/team/config");

export const updateTeamConfig = (config: TeamConfigUpdate) =>
  post<TeamConfig>("ai/team/config", config);

function parseTeamStreamFrame(line: string): TeamStreamFrame | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith("data:")) return null;
  const raw = trimmed.slice(5).trim();
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as TeamStreamFrame;
    if (parsed.type === "event" && parsed.event) return parsed;
    if (parsed.type === "result" && parsed.data) return parsed;
    if (parsed.type === "error" && typeof parsed.message === "string") return parsed;
    if (parsed.type === "done") return parsed;
  } catch {
    return null;
  }
  return null;
}

/** Stream one team analysis, including task lifecycle and the canonical result. */
export async function* runTeamAnalysisStream(
  symbol: string,
  exchange: string,
  market_data?: Record<string, unknown>,
  options: TeamRunOptions = {},
  signal?: AbortSignal,
): AsyncGenerator<TeamStreamFrame, void, unknown> {
  const resp = await fetch(`${getBase()}/api/v1/ai/team/analyse/stream`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify({
      symbol,
      exchange,
      ...(market_data ? { market_data } : {}),
      ...options,
    }),
    signal,
  });

  if (!resp.ok) {
    let message = `Team analysis failed (HTTP ${resp.status})`;
    try {
      const payload = (await resp.json()) as { message?: unknown };
      if (typeof payload.message === "string" && payload.message) message = payload.message;
    } catch {
      // Keep the status-derived message for non-JSON failures.
    }
    throw new Error(message);
  }

  const reader = resp.body?.getReader();
  if (!reader) throw new Error("No readable stream in team analysis response.");

  const decoder = new TextDecoder();
  let buffer = "";
  let sawResult = false;
  let sawDone = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newlineIndex = buffer.indexOf("\n");
      while (newlineIndex !== -1) {
        const line = buffer.slice(0, newlineIndex);
        buffer = buffer.slice(newlineIndex + 1);
        const frame = parseTeamStreamFrame(line);
        if (frame) {
          sawResult ||= frame.type === "result";
          sawDone ||= frame.type === "done";
          yield frame;
        }
        newlineIndex = buffer.indexOf("\n");
      }
    }
    const tail = parseTeamStreamFrame(buffer);
    if (tail) {
      sawResult ||= tail.type === "result";
      sawDone ||= tail.type === "done";
      yield tail;
    }
    if (!sawResult || !sawDone) {
      throw new Error("Team analysis stream ended before the final result and completion frames.");
    }
  } finally {
    try {
      await reader.cancel();
    } catch {
      // Already cancelled or closed.
    }
    reader.releaseLock();
  }
}

// ---------------------------------------------------------------------------
// AI agent backends (agent_backends registry — /ai/agents/*)
//
// The catalogue lists six backends in two families: LLM chat/completion
// providers (claude-code, claude-code-oauth, cerebras) that are configured via
// Settings and driven through the AI advisor, and CLI/ACP agent runtimes
// (codex, antigravity, hermes) detected by a binary on PATH and run as a
// streamed turn. `runAgent` speaks Server-Sent Events; the honest error cases
// (LLM backend, unknown id, not-installed) come back as JSON and throw the
// backend's actionable message.
// ---------------------------------------------------------------------------

/** Backend family: chat/completion LLM vs stand-alone/ACP agent runtime. */
export type BackendKind = "llm" | "cli_agent" | "acp_agent";

/** Live detection status reported by the backend for a single agent backend. */
export type BackendStatus = "ready" | "not_installed" | "needs_config" | "installed";

/** One catalogue entry from GET /ai/agents/backends. */
export interface BackendItem {
  id: string;
  display_name: string;
  kind: BackendKind;
  auth_mode: string;
  description: string;
  llm_provider: string | null;
  detect_binaries: string[];
  invocation: string[];
  requires_binary: boolean;
  status: BackendStatus;
}

/** One decoded Server-Sent Event frame from a streaming agent turn. */
export type AgentEventKind = "output" | "tool" | "error" | "done";

export interface AgentEvent {
  kind: AgentEventKind;
  text: string | null;
  data: Record<string, unknown> | null;
}

/** List every supported agent backend with its live detection status. */
export const getAgentBackends = () =>
  get<{ backends: BackendItem[] }>("ai/agents/backends");

/**
 * Extract the backend's actionable error message from a non-streaming JSON
 * response (the honest LLM-backend / unknown-id / not-installed cases) and
 * throw it, falling back to the status code when there is no message.
 */
async function throwAgentRunError(resp: Response): Promise<never> {
  let message: string | null = null;
  try {
    const body: unknown = await resp.json();
    if (body !== null && typeof body === "object") {
      const record = body as Record<string, unknown>;
      if (typeof record.message === "string") message = record.message;
      else if (typeof record.error === "string") message = record.error;
    }
  } catch {
    // Not a JSON body — fall through to the generic message.
  }
  throw new Error(message ?? `Agent run failed: HTTP ${resp.status}`);
}

/**
 * Parse a single SSE line into an {@link AgentEvent}, or null for the blank
 * separator lines and any non-`data:` frame. Each frame the backend emits is
 * `data: {json}\n\n`, so splitting on newlines yields one payload line plus
 * blank lines.
 */
function parseAgentEvent(line: string): AgentEvent | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith("data:")) return null;
  const raw = trimmed.slice(5).trim();
  if (!raw) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object") return null;

  const record = parsed as Record<string, unknown>;
  const kind = record.kind;
  if (kind !== "output" && kind !== "tool" && kind !== "error" && kind !== "done") {
    return null;
  }
  return {
    kind,
    text: typeof record.text === "string" ? record.text : null,
    data:
      record.data !== null && typeof record.data === "object"
        ? (record.data as Record<string, unknown>)
        : null,
  };
}

/**
 * Run one turn on an installed CLI/ACP agent backend, yielding each decoded
 * {@link AgentEvent} as it streams in. The stream always ends with a `done`
 * event. Honest error responses (an LLM backend, an unknown id, or a
 * not-installed agent) come back as JSON, not a stream, and are surfaced by
 * throwing the backend's message — never a fabricated event.
 */
export async function* runAgent(
  backendId: string,
  prompt: string,
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent, void, unknown> {
  const resp = await fetch(`${getBase()}/api/v1/ai/agents/run`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify({ backend_id: backendId, prompt }),
    signal,
  });

  if (!resp.ok) {
    await throwAgentRunError(resp);
  }

  const reader = resp.body?.getReader();
  if (!reader) {
    throw new Error("No readable stream in agent run response.");
  }

  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let newlineIndex = buffer.indexOf("\n");
      while (newlineIndex !== -1) {
        const line = buffer.slice(0, newlineIndex);
        buffer = buffer.slice(newlineIndex + 1);
        const event = parseAgentEvent(line);
        if (event) yield event;
        newlineIndex = buffer.indexOf("\n");
      }
    }
    // Flush any trailing buffered frame not terminated by a newline.
    const tail = parseAgentEvent(buffer);
    if (tail) yield tail;
  } finally {
    try {
      await reader.cancel();
    } catch {
      // Already cancelled/closed.
    }
    reader.releaseLock();
  }
}

// ---------------------------------------------------------------------------
// Market Sentiment Dashboard (sentiment.py — MarketSummary schema)
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

/**
 * Persist the vault path (workspace-backed; the FLINTTRADE_OBSIDIAN_VAULT
 * environment variable, when set, overrides it and the backend says so).
 * An empty string clears the stored path.
 */
export const saveObsidianVaultPath = (vaultPath: string) =>
  post<{ vault_path: string; env_override: boolean }>("ai/obsidian/config", {
    vault_path: vaultPath,
  });

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

// ---------------------------------------------------------------------------
// Autonomous agent control plane (/ai/agent/*) — live mode, gated, OFF by
// default (workspace ai.autonomous_agent.enabled). The agent runs as its own
// ACL'd principal; every order traverses the full gated execution path.
// ---------------------------------------------------------------------------

export interface AgentPositionDetails {
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  action: string;
  quantity: number;
}

export interface AgentSnapshot {
  enabled: boolean;
  running: boolean;
  started_at: string;
  params: Record<string, unknown>;
  actor_id: string;
  agent_status?: string;
  daily_pnl?: number;
  cycle_count?: number;
  active_positions?: Record<string, number>;
  position_details?: Record<string, AgentPositionDetails>;
  trade_counts?: Record<string, number>;
  last_signals?: Record<string, string>;
  squared_off?: boolean;
  stop_loss_hit?: boolean;
}

export interface AgentStartParams {
  symbols: string[];
  exchange?: string;
  product?: string;
  max_position_size?: number;
  stop_loss_pct?: number;
  take_profit_pct?: number;
  daily_stop_loss?: number;
  max_trades_per_symbol?: number;
  cycle_interval_sec?: number;
  broker?: string;
  account_id?: string;
}

function withAgentBrokerTarget(params: AgentStartParams): AgentStartParams {
  if (params.broker || params.account_id) return params;
  const mode = useModeStore.getState().mode;
  const apiKey = useConnectionStore.getState().apiKey;
  const nativeTarget = pickNativeBrokerOrderTarget(mode, apiKey);
  if (nativeTarget) return { ...params, ...nativeTarget };
  // Fail closed like postOrder / startSmartRoute: an autonomous agent must never
  // START against a silently-defaulted target. AgentPanel passes no explicit
  // broker/account_id and has no target selector, so in the post-reload
  // unconfirmed window a bare start would bind the whole session to the backend's
  // brokers.execution.default rather than the operator's selected native account.
  assertNativeWriteTargetReadyOrThrow(mode, apiKey);
  return params;
}

/** Live agent/session snapshot — honest `{running: false}` shape when idle. */
export const getAgentStatus = () => get<AgentSnapshot>("ai/agent/status");

/** Start a trading session (202). Backend refusals carry actionable messages. */
export const startAgent = (params: AgentStartParams) =>
  post<AgentSnapshot>("ai/agent/start", withAgentBrokerTarget(params));

/** Request a stop; squares off tracked positions unless squareOff is false. */
export const stopAgent = (squareOff = true) =>
  post<AgentSnapshot>("ai/agent/stop", { square_off: squareOff });
