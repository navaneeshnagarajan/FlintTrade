/**
 * TradeCopierWidget — Multi-account trade copying for the /ditto route.
 *
 * Manages trade copying from one source account to multiple target accounts.
 *
 * Features:
 *   - Source account selector (dropdown)
 *   - Target accounts with checkbox + lot multiplier per account
 *   - Copy mode: "Mirror" (same qty) or "Proportional" (ratio-based)
 *   - Active / paused toggle per target account
 *   - Copy log: recent events with status (success / failed / skipped)
 *   - Risk filter panel: max position size, max daily loss, symbol whitelist
 *
 * Data persistence:
 *   - All config stored in localStorage under "flinttrade:tradecopier"
 *   - Copy log kept in component state (session only; cleared on unmount)
 *   - Actual execution is handled by the Ditto backend — this widget only
 *     manages the configuration that the backend reads.
 *
 * Status indicators:
 *   - Green dot  = active (copying enabled)
 *   - Amber dot  = paused (target manually paused)
 *   - Red dot    = disconnected (account not connected)
 */

import {
  useState,
  useEffect,
  useCallback,
  useId,
  memo,
} from "react";
import {
  Copy,
  Play,
  Pause,
  Trash2,
  Plus,
  CheckCircle2,
  XCircle,
  MinusCircle,
  AlertCircle,
  Settings2,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type CopyMode = "mirror" | "proportional";
type AccountStatus = "active" | "paused" | "disconnected";
type CopyEventStatus = "success" | "failed" | "skipped";

interface TargetAccount {
  id: string;
  name: string;
  status: AccountStatus;
  enabled: boolean;
  multiplier: number; // lot multiplier (1 = same, 2 = double, etc.)
}

interface CopyEvent {
  id: string;
  timestamp: string; // ISO string
  symbol: string;
  action: "BUY" | "SELL";
  qty: number;
  targetAccountId: string;
  targetAccountName: string;
  status: CopyEventStatus;
  reason?: string; // for failed/skipped
}

interface RiskFilter {
  maxPositionSize: number | null; // max lots per position
  maxDailyLoss: number | null;    // INR
  symbolWhitelist: string;        // comma-separated symbols, empty = all
}

interface CopierConfig {
  sourceAccountId: string;
  copyMode: CopyMode;
  targets: TargetAccount[];
  riskFilter: RiskFilter;
}

// ---------------------------------------------------------------------------
// Sample accounts (before real Ditto backend is wired up)
// ---------------------------------------------------------------------------

const SAMPLE_ACCOUNTS: Array<{ id: string; name: string }> = [
  { id: "acc-1", name: "Primary (Zerodha)" },
  { id: "acc-2", name: "Family (Angel One)" },
  { id: "acc-3", name: "HUF (Upstox)" },
];

const DEFAULT_TARGETS: TargetAccount[] = [
  { id: "acc-2", name: "Family (Angel One)", status: "active", enabled: true, multiplier: 1 },
  { id: "acc-3", name: "HUF (Upstox)", status: "paused", enabled: false, multiplier: 0.5 },
];

const STORAGE_KEY = "flinttrade:tradecopier";

function loadConfig(): CopierConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as CopierConfig;
  } catch {
    // Ignore parse errors
  }
  return {
    sourceAccountId: SAMPLE_ACCOUNTS[0].id,
    copyMode: "mirror",
    targets: DEFAULT_TARGETS,
    riskFilter: { maxPositionSize: null, maxDailyLoss: null, symbolWhitelist: "" },
  };
}

function saveConfig(config: CopierConfig): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch {
    // localStorage quota exceeded — ignore
  }
}

// ---------------------------------------------------------------------------
// Status dot
// ---------------------------------------------------------------------------

function StatusDot({ status }: { status: AccountStatus }) {
  const colour =
    status === "active"
      ? "bg-profit"
      : status === "paused"
        ? "bg-warning"
        : "bg-loss";
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full flex-none ${colour}`}
      title={status}
      aria-label={`Status: ${status}`}
    />
  );
}

// ---------------------------------------------------------------------------
// Copy event status icon
// ---------------------------------------------------------------------------

function EventStatusIcon({ status }: { status: CopyEventStatus }) {
  if (status === "success") return <CheckCircle2 size={12} className="text-profit flex-none" />;
  if (status === "failed")  return <XCircle size={12} className="text-loss flex-none" />;
  return <MinusCircle size={12} className="text-warning flex-none" />;
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function TradeCopierWidget() {
  const [config, setConfig] = useState<CopierConfig>(loadConfig);
  const [log, setLog] = useState<CopyEvent[]>([]);
  const [showRisk, setShowRisk] = useState(false);
  const [newTargetId, setNewTargetId] = useState<string>("");

  const formId = useId();

  // Persist config whenever it changes
  useEffect(() => {
    saveConfig(config);
  }, [config]);

  // ---------------------------------------------------------------------------
  // Source account
  // ---------------------------------------------------------------------------

  const handleSourceChange = useCallback((id: string) => {
    setConfig((c) => ({ ...c, sourceAccountId: id }));
  }, []);

  // ---------------------------------------------------------------------------
  // Copy mode
  // ---------------------------------------------------------------------------

  const handleModeChange = useCallback((mode: CopyMode) => {
    setConfig((c) => ({ ...c, copyMode: mode }));
  }, []);

  // ---------------------------------------------------------------------------
  // Target account management
  // ---------------------------------------------------------------------------

  const handleToggleTarget = useCallback((targetId: string, enabled: boolean) => {
    setConfig((c) => ({
      ...c,
      targets: c.targets.map((t) =>
        t.id === targetId ? { ...t, enabled } : t,
      ),
    }));
  }, []);

  const handleSetStatus = useCallback((targetId: string, status: AccountStatus) => {
    setConfig((c) => ({
      ...c,
      targets: c.targets.map((t) =>
        t.id === targetId ? { ...t, status } : t,
      ),
    }));
  }, []);

  const handleMultiplierChange = useCallback((targetId: string, value: string) => {
    const num = parseFloat(value);
    if (!isFinite(num) || num <= 0) return;
    setConfig((c) => ({
      ...c,
      targets: c.targets.map((t) =>
        t.id === targetId ? { ...t, multiplier: num } : t,
      ),
    }));
  }, []);

  const handleRemoveTarget = useCallback((targetId: string) => {
    setConfig((c) => ({
      ...c,
      targets: c.targets.filter((t) => t.id !== targetId),
    }));
  }, []);

  const handleAddTarget = useCallback(() => {
    if (!newTargetId) return;
    const acct = SAMPLE_ACCOUNTS.find((a) => a.id === newTargetId);
    if (!acct) return;
    if (config.targets.some((t) => t.id === newTargetId)) return;
    setConfig((c) => ({
      ...c,
      targets: [
        ...c.targets,
        { id: acct.id, name: acct.name, status: "active", enabled: true, multiplier: 1 },
      ],
    }));
    setNewTargetId("");
  }, [newTargetId, config.targets]);

  // ---------------------------------------------------------------------------
  // Risk filter
  // ---------------------------------------------------------------------------

  const handleRiskChange = useCallback(
    (field: keyof RiskFilter, value: string) => {
      setConfig((c) => ({
        ...c,
        riskFilter: {
          ...c.riskFilter,
          [field]: field === "symbolWhitelist"
            ? value
            : value === "" ? null : parseFloat(value),
        },
      }));
    },
    [],
  );

  // ---------------------------------------------------------------------------
  // Mock "copy" action for demo — adds a log entry
  // ---------------------------------------------------------------------------

  const handleTestCopy = useCallback(() => {
    const symbols = ["NIFTY24APR25000CE", "BANKNIFTY24APR50000PE", "NIFTY24APR24800CE"];
    const actions: Array<"BUY" | "SELL"> = ["BUY", "SELL"];
    const statuses: CopyEventStatus[] = ["success", "failed", "skipped"];
    const activeTargets = config.targets.filter((t) => t.enabled && t.status === "active");

    if (activeTargets.length === 0) return;

    const newEvents: CopyEvent[] = activeTargets.map((t) => ({
      id: `${Date.now()}-${t.id}`,
      timestamp: new Date().toISOString(),
      symbol: symbols[Math.floor(Math.random() * symbols.length)],
      action: actions[Math.floor(Math.random() * actions.length)],
      qty: Math.floor(Math.random() * 5 + 1) * 50,
      targetAccountId: t.id,
      targetAccountName: t.name,
      status: statuses[Math.floor(Math.random() * statuses.length)],
      reason: Math.random() < 0.3 ? "Exceeded max daily loss limit" : undefined,
    }));

    setLog((prev) => [...newEvents, ...prev].slice(0, 50));
  }, [config.targets]);

  // ---------------------------------------------------------------------------
  // Derived
  // ---------------------------------------------------------------------------

  const availableToAdd = SAMPLE_ACCOUNTS.filter(
    (a) => a.id !== config.sourceAccountId && !config.targets.some((t) => t.id === a.id),
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" data-testid="tradecopier-widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-3 py-2 bg-surface-card border-b border-border-default">
        <Copy size={13} className="text-accent flex-none" />
        <span className="text-sm font-medium text-text-primary">Trade Copier</span>
        <div className="flex-1" />
        {/* Test button for demo */}
        <button
          onClick={handleTestCopy}
          className="px-2 py-0.5 text-xxs bg-accent/15 text-accent rounded border border-accent/30 hover:bg-accent/25 transition-colors"
          title="Simulate a copy event"
          data-testid="test-copy-btn"
        >
          Test Copy
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col">

        {/* Source + Mode row */}
        <div className="px-3 py-2 border-b border-border-default flex flex-col gap-2">
          {/* Source account */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-muted w-14 flex-none">Source</span>
            <select
              value={config.sourceAccountId}
              onChange={(e) => handleSourceChange(e.target.value)}
              className="flex-1 px-2 py-1 text-xs bg-surface-hover border border-border-default rounded text-text-primary focus:outline-none focus:border-accent/50"
              data-testid="source-select"
            >
              {SAMPLE_ACCOUNTS.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
            <StatusDot status="active" />
          </div>

          {/* Copy mode */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-muted w-14 flex-none">Mode</span>
            <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
              {(["mirror", "proportional"] as CopyMode[]).map((m) => (
                <button
                  key={m}
                  onClick={() => handleModeChange(m)}
                  className={`px-2 py-0.5 text-xxs font-medium capitalize transition-colors ${
                    m === config.copyMode
                      ? "bg-accent/15 text-accent"
                      : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                  }`}
                  data-testid={`mode-${m}`}
                >
                  {m === "mirror" ? "Mirror" : "Proportional"}
                </button>
              ))}
            </div>
            {config.copyMode === "proportional" && (
              <span className="text-xxs text-text-muted italic">ratio via multiplier</span>
            )}
          </div>
        </div>

        {/* Target accounts */}
        <div className="px-3 py-2 flex flex-col gap-1.5">
          <div className="flex items-center gap-1 mb-1">
            <span className="text-xs font-medium text-text-primary">Target Accounts</span>
            <Badge variant="outline" className="text-xxs px-1 py-0">{config.targets.length}</Badge>
          </div>

          {config.targets.length === 0 && (
            <div className="text-xxs text-text-muted italic py-2 text-center">
              No target accounts configured
            </div>
          )}

          {config.targets.map((target) => (
            <div
              key={target.id}
              className="flex items-center gap-2 px-2 py-1.5 bg-surface-card rounded border border-border-default"
              data-testid={`target-${target.id}`}
            >
              <StatusDot status={target.status} />

              <span className="flex-1 text-xs text-text-primary truncate">{target.name}</span>

              {/* Multiplier */}
              <div className="flex items-center gap-1">
                <span className="text-xxs text-text-muted">×</span>
                <input
                  type="number"
                  min={0.1}
                  step={0.5}
                  value={target.multiplier}
                  onChange={(e) => handleMultiplierChange(target.id, e.target.value)}
                  className="w-12 px-1 py-0.5 text-xs bg-surface-hover border border-border-default rounded text-text-primary text-center font-mono tabular-nums focus:outline-none focus:border-accent/50"
                  title="Lot multiplier"
                  data-testid={`multiplier-${target.id}`}
                />
              </div>

              {/* Pause / Resume */}
              <button
                onClick={() =>
                  handleSetStatus(
                    target.id,
                    target.status === "paused" ? "active" : "paused",
                  )
                }
                className="p-0.5 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
                title={target.status === "paused" ? "Resume" : "Pause"}
                data-testid={`status-toggle-${target.id}`}
              >
                {target.status === "paused" ? <Play size={11} /> : <Pause size={11} />}
              </button>

              {/* Enable/Disable switch */}
              <Switch
                checked={target.enabled}
                onCheckedChange={(v) => handleToggleTarget(target.id, v)}
                aria-label={`Enable copying to ${target.name}`}
                data-testid={`enable-${target.id}`}
              />

              {/* Remove */}
              <button
                onClick={() => handleRemoveTarget(target.id)}
                className="p-0.5 rounded text-text-muted hover:text-loss hover:bg-loss/10 transition-colors"
                title="Remove target"
                data-testid={`remove-${target.id}`}
              >
                <Trash2 size={11} />
              </button>
            </div>
          ))}

          {/* Add target */}
          {availableToAdd.length > 0 && (
            <div className="flex items-center gap-1.5 mt-1">
              <select
                value={newTargetId}
                onChange={(e) => setNewTargetId(e.target.value)}
                className="flex-1 px-2 py-0.5 text-xs bg-surface-hover border border-border-default rounded text-text-primary focus:outline-none focus:border-accent/50"
                data-testid="add-target-select"
              >
                <option value="">Add account...</option>
                {availableToAdd.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
              <button
                onClick={handleAddTarget}
                disabled={!newTargetId}
                className="p-1 rounded bg-accent/15 text-accent border border-accent/30 hover:bg-accent/25 transition-colors disabled:opacity-40"
                title="Add target account"
                data-testid="add-target-btn"
              >
                <Plus size={12} />
              </button>
            </div>
          )}
        </div>

        {/* Risk filter (collapsible) */}
        <div className="px-3 py-1.5 border-t border-border-default">
          <button
            onClick={() => setShowRisk((v) => !v)}
            className="flex items-center gap-1.5 w-full text-xs text-text-secondary hover:text-text-primary transition-colors"
            data-testid="risk-toggle"
          >
            <Settings2 size={11} />
            <span className="font-medium">Risk Filters</span>
            <div className="flex-1" />
            {showRisk ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>

          {showRisk && (
            <div className="mt-2 flex flex-col gap-2" data-testid="risk-panel">
              <div className="grid grid-cols-2 gap-2">
                <label className="flex flex-col gap-0.5">
                  <span className="text-xxs text-text-muted">Max Position (lots)</span>
                  <input
                    id={`${formId}-maxpos`}
                    type="number"
                    min={1}
                    value={config.riskFilter.maxPositionSize ?? ""}
                    onChange={(e) => handleRiskChange("maxPositionSize", e.target.value)}
                    placeholder="No limit"
                    className="px-2 py-1 text-xs bg-surface-hover border border-border-default rounded text-text-primary font-mono placeholder:text-text-muted focus:outline-none focus:border-accent/50"
                    data-testid="max-position-input"
                  />
                </label>
                <label className="flex flex-col gap-0.5">
                  <span className="text-xxs text-text-muted">Max Daily Loss (₹)</span>
                  <input
                    id={`${formId}-maxloss`}
                    type="number"
                    min={0}
                    value={config.riskFilter.maxDailyLoss ?? ""}
                    onChange={(e) => handleRiskChange("maxDailyLoss", e.target.value)}
                    placeholder="No limit"
                    className="px-2 py-1 text-xs bg-surface-hover border border-border-default rounded text-text-primary font-mono placeholder:text-text-muted focus:outline-none focus:border-accent/50"
                    data-testid="max-daily-loss-input"
                  />
                </label>
              </div>
              <label className="flex flex-col gap-0.5">
                <span className="text-xxs text-text-muted">Symbol Whitelist (comma-separated, empty = all)</span>
                <input
                  id={`${formId}-whitelist`}
                  type="text"
                  value={config.riskFilter.symbolWhitelist}
                  onChange={(e) => handleRiskChange("symbolWhitelist", e.target.value)}
                  placeholder="NIFTY, BANKNIFTY, ..."
                  className="px-2 py-1 text-xs bg-surface-hover border border-border-default rounded text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent/50"
                  data-testid="symbol-whitelist-input"
                />
              </label>
              {config.riskFilter.symbolWhitelist.trim() && (
                <div className="flex flex-wrap gap-1">
                  {config.riskFilter.symbolWhitelist
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean)
                    .map((s) => (
                      <Badge key={s} variant="outline" className="text-xxs px-1.5 py-0">
                        {s}
                      </Badge>
                    ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Copy log */}
        <div className="flex-1 min-h-0 border-t border-border-default flex flex-col">
          <div className="flex items-center gap-1.5 px-3 py-1.5">
            <span className="text-xs font-medium text-text-primary">Copy Log</span>
            <Badge variant="outline" className="text-xxs px-1 py-0">{log.length}</Badge>
            {log.length > 0 && (
              <button
                onClick={() => setLog([])}
                className="ml-auto text-xxs text-text-muted hover:text-loss transition-colors"
                data-testid="clear-log-btn"
              >
                Clear
              </button>
            )}
          </div>

          <div className="flex-1 overflow-y-auto" data-testid="copy-log">
            {log.length === 0 ? (
              <div className="flex items-center justify-center h-16 text-xxs text-text-muted italic">
                No copy events yet
              </div>
            ) : (
              <div className="flex flex-col divide-y divide-border-default">
                {log.map((event) => (
                  <div key={event.id} className="flex items-start gap-2 px-3 py-1.5">
                    <EventStatusIcon status={event.status} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className={`text-xxs font-mono font-semibold ${
                          event.action === "BUY" ? "text-profit" : "text-loss"
                        }`}>
                          {event.action}
                        </span>
                        <span className="text-xxs text-text-primary truncate">{event.symbol}</span>
                        <span className="text-xxs text-text-muted font-mono">{event.qty}</span>
                        <span className="text-xxs text-text-muted">→ {event.targetAccountName}</span>
                      </div>
                      {event.reason && (
                        <div className="flex items-center gap-1 mt-0.5">
                          <AlertCircle size={9} className="text-warning flex-none" />
                          <span className="text-xxs text-warning truncate">{event.reason}</span>
                        </div>
                      )}
                    </div>
                    <span className="text-xxs text-text-muted flex-none font-mono tabular-nums">
                      {new Date(event.timestamp).toLocaleTimeString("en-IN", {
                        hour: "2-digit", minute: "2-digit", second: "2-digit",
                        hour12: false,
                      })}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default memo(TradeCopierWidget);
