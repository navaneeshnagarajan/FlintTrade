/**
 * AdminRoute — dev-only /admin dashboard.
 *
 * Only accessible when `import.meta.env.DEV` is true.
 * Provides internal visibility into package health, widget registry,
 * endpoint status, feature flags, absorption tracker, and dependencies.
 */

import { useState, useEffect, useRef, useCallback, type JSX } from "react";
import { z } from "zod";
import { safeParse } from "@/lib/safeParse";
import { ArrowLeft, Package, LayoutGrid, Globe, Flag, GitBranch, Network, ScrollText, X, Activity } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { SystemMetricsPanel } from "./admin/SystemMetricsPanel";
import { useAuthStore } from "@/stores/authStore";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PackageInfo {
  name: string;
  type: "python" | "react" | "rust";
  status: "active" | "stub" | "planned";
  testCount: number;
  testFiles: number;
}

interface WidgetInfo {
  id: string;
  name: string;
  category: string;
  status: "live" | "stub" | "planned";
}

interface EndpointInfo {
  method: string;
  path: string;
  status: "wired" | "stub" | "planned";
}

interface FeatureInfo {
  name: string;
  status: "live" | "preview" | "locked";
  route: string;
}

interface RepoInfo {
  status: string;
  target_package: string;
  absorbed_patterns: string[];
  last_examined: string | null;
  upstream_url: string;
  notes: string;
}

interface AbsorptionData {
  version: string;
  last_updated: string;
  total_repos: number;
  repos: Record<string, RepoInfo>;
}

interface LogEntry {
  timestamp: string;
  level: "ERROR" | "WARNING" | "INFO" | "DEBUG";
  message: string;
  request_id?: string;
}

const logEntrySchema = z.object({
  timestamp: z.string(),
  level: z.enum(["ERROR", "WARNING", "INFO", "DEBUG"]),
  message: z.string(),
  request_id: z.string().optional(),
}) satisfies z.ZodType<LogEntry>;

// ---------------------------------------------------------------------------
// Tab IDs
// ---------------------------------------------------------------------------

type TabId = "packages" | "widgets" | "endpoints" | "features" | "absorption" | "deps" | "logs" | "system";

const TABS: { id: TabId; label: string; icon: typeof Package }[] = [
  { id: "system", label: "System", icon: Activity },
  { id: "packages", label: "Packages", icon: Package },
  { id: "widgets", label: "Widgets", icon: LayoutGrid },
  { id: "endpoints", label: "Endpoints", icon: Globe },
  { id: "features", label: "Features", icon: Flag },
  { id: "absorption", label: "Absorption", icon: GitBranch },
  { id: "deps", label: "Dependencies", icon: Network },
  { id: "logs", label: "Logs", icon: ScrollText },
];

// ---------------------------------------------------------------------------
// Introspection data (fetched from backend)
// ---------------------------------------------------------------------------

interface IntrospectData {
  packages: PackageInfo[];
  endpoints: EndpointInfo[];
  endpoint_count: number;
  package_count: number;
}

const EMPTY_INTROSPECT: IntrospectData = {
  packages: [],
  endpoints: [],
  endpoint_count: 0,
  package_count: 0,
};

function isDemoAuthSession(): boolean {
  const token = useAuthStore.getState().token;
  return token === "demo-user" || token === "dev-bypass";
}

function useIntrospect(): { data: IntrospectData | null; loading: boolean; error: string | null } {
  const [data, setData] = useState<IntrospectData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isDemoAuthSession()) {
      setData(EMPTY_INTROSPECT);
      setLoading(false);
      return;
    }

    fetch("/ft-api/v1/admin/introspect")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<{ status: string; data: IntrospectData }>;
      })
      .then((json) => setData(json.data))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  return { data, loading, error };
}

// ---------------------------------------------------------------------------
// Static Data (widgets & features — change rarely)
// ---------------------------------------------------------------------------

const WIDGETS: WidgetInfo[] = [
  // Trading
  { id: "dashboard", name: "Dashboard", category: "Trading", status: "live" },
  { id: "scalper", name: "Scalper", category: "Trading", status: "live" },
  { id: "positions", name: "Positions", category: "Trading", status: "live" },
  { id: "orders", name: "Orders", category: "Trading", status: "live" },
  { id: "holdings", name: "Holdings", category: "Trading", status: "live" },
  { id: "tradebook", name: "Trade Book", category: "Trading", status: "live" },
  { id: "orderpad", name: "Order Pad", category: "Trading", status: "live" },
  { id: "mtmmonitor", name: "MTM Monitor", category: "Trading", status: "live" },
  { id: "riskpanel", name: "Risk Panel", category: "Trading", status: "live" },
  { id: "actioncenter", name: "Action Center", category: "Trading", status: "live" },
  // Analysis
  { id: "chart", name: "Chart", category: "Analysis", status: "live" },
  { id: "optionchain", name: "Option Chain", category: "Analysis", status: "live" },
  { id: "oichart", name: "OI Chart", category: "Analysis", status: "live" },
  { id: "straddle", name: "Straddle", category: "Analysis", status: "live" },
  { id: "depth", name: "Depth", category: "Analysis", status: "live" },
  { id: "greeks", name: "Greeks", category: "Analysis", status: "live" },
  { id: "sectormap", name: "Sector Map", category: "Analysis", status: "live" },
  { id: "gammadensity", name: "Dealer Gamma", category: "Analysis", status: "live" },
  { id: "volsurface", name: "Vol Surface", category: "Analysis", status: "live" },
  { id: "ivsmile", name: "IV Smile", category: "Analysis", status: "live" },
  { id: "straddlepnl", name: "Straddle P&L", category: "Analysis", status: "live" },
  { id: "oiprofile", name: "OI Profile", category: "Analysis", status: "live" },
  { id: "orderflow", name: "Order Flow", category: "Analysis", status: "live" },
  // Utility
  { id: "watchlist", name: "Watchlist", category: "Utility", status: "live" },
  { id: "calculator", name: "Calculator", category: "Utility", status: "live" },
  { id: "news", name: "News Feed", category: "Utility", status: "live" },
  { id: "ticker", name: "Ticker", category: "Utility", status: "live" },
  { id: "aiadvisor", name: "AI Advisor", category: "Utility", status: "live" },
];

const FEATURES: FeatureInfo[] = [
  { name: "Dockview Workspace", status: "live", route: "/trade" },
  { name: "Multi-broker Gateway", status: "live", route: "/settings" },
  { name: "Option Chain (real-time)", status: "live", route: "/trade" },
  { name: "Dealer Gamma (GEX + density)", status: "live", route: "/trade" },
  { name: "IV Smile / Vol Surface", status: "live", route: "/trade" },
  { name: "Security Monitoring", status: "live", route: "/settings" },
  { name: "P&L Tracker", status: "live", route: "/trade" },
  { name: "AI Advisor Chat", status: "live", route: "/ai" },
  { name: "Backtest Lab", status: "live", route: "/lab" },
  { name: "Flow Builder", status: "live", route: "/automate" },
  { name: "Strategy Builder", status: "live", route: "/automate" },
  { name: "Investor Dashboard", status: "live", route: "/invest" },
  { name: "Learn Center", status: "live", route: "/learn" },
  { name: "Voice Trading", status: "locked", route: "/trade" },
  { name: "Telegram Kill Switch", status: "locked", route: "/automate" },
  { name: "Multi-account Mirroring", status: "locked", route: "/settings" },
  { name: "AI Swarm Intelligence", status: "locked", route: "/ai" },
  { name: "Rust Tick Engine", status: "locked", route: "/trade" },
];

// ---------------------------------------------------------------------------
// Dependency graph (text representation)
// ---------------------------------------------------------------------------

const DEPENDENCY_GRAPH = `
FlintTrade Dependency Graph
===========================

terminal (React)
  +-- api.ts ------> OpenAlgo REST (port 5000)
  +-- websocket.ts -> OpenAlgo WS (port 8765)
  +-- ft-api -------> core/app.py (port 5100)

core
  +-- openalgo_client -> OpenAlgo REST API
  +-- config ----------> workspace.json + .env fallback
  +-- security --------> rate limiting, threat detection
  +-- monitoring ------> health, traffic, latency

gateway
  +-- core (config, models)
  +-- native adapter contract + routing
  +-- Dhan direct scaffold (SDK calls gated)
  +-- OpenAlgo-compatible bridge shims

engine
  +-- core (OpenAlgo client, models)
  +-- data (audit logger)

screener
  +-- core (OpenAlgo client)
  +-- historical (OHLCV data)

backtest-engine
  +-- core (models, config)
  +-- historical (OHLCV data)
  +-- indicators (TA-Lib, Numba)

ai
  +-- core (config, models)
  +-- data (context for RAG)

integration
  +-- core (OpenAlgo client)
  +-- engine (order router)

automation
  +-- core (config)
  +-- engine (scheduler)
  +-- integration (webhooks)

ditto
  +-- core (OpenAlgo client)
  +-- engine (safety system)

data
  +-- core (config, models)

historical
  +-- core (config)
  +-- data (DuckDB storage)

indicators
  +-- (standalone — TA-Lib + Numba)

tick-engine (Rust/PyO3)
  +-- (standalone — future)
`.trim();

// ---------------------------------------------------------------------------
// Status badge component
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }): JSX.Element {
  const colors: Record<string, string> = {
    active: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    live: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    wired: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    integrated: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    verified: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    preview: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    examined: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    stub: "bg-zinc-500/20 text-zinc-400 border-zinc-500/30",
    planned: "bg-zinc-500/20 text-zinc-400 border-zinc-500/30",
    unexamined: "bg-zinc-500/20 text-zinc-400 border-zinc-500/30",
    locked: "bg-red-500/20 text-red-400 border-red-500/30",
    deferred: "bg-red-500/20 text-red-400 border-red-500/30",
  };
  const cls = colors[status] ?? "bg-zinc-500/20 text-zinc-400 border-zinc-500/30";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-medium rounded border ${cls}`}>
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Tab panels
// ---------------------------------------------------------------------------

function PackagesPanel({ packages, loading, error }: {
  packages: PackageInfo[];
  loading: boolean;
  error: string | null;
}): JSX.Element {
  if (loading) {
    return <p className="text-text-secondary text-sm p-4">Loading package data...</p>;
  }
  if (error) {
    return (
      <div className="p-4 text-sm">
        <p className="text-red-400">Failed to load packages: {error}</p>
        <p className="text-text-muted mt-1">Ensure the FlintTrade backend is running (port 5100).</p>
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-text-secondary">
            <th className="py-2 px-3 font-medium">Package</th>
            <th className="py-2 px-3 font-medium">Type</th>
            <th className="py-2 px-3 font-medium">Status</th>
            <th className="py-2 px-3 font-medium text-right">Test Files</th>
            <th className="py-2 px-3 font-medium text-right">Tests</th>
          </tr>
        </thead>
        <tbody>
          {packages.map((pkg) => (
            <tr key={pkg.name} className="border-b border-border/50 hover:bg-surface-hover">
              <td className="py-2 px-3 font-mono text-text-primary">{pkg.name}</td>
              <td className="py-2 px-3 text-text-secondary">{pkg.type}</td>
              <td className="py-2 px-3"><StatusBadge status={pkg.status} /></td>
              <td className="py-2 px-3 text-right font-mono text-text-secondary">{pkg.testFiles}</td>
              <td className="py-2 px-3 text-right font-mono text-text-secondary">{pkg.testCount}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WidgetsPanel(): JSX.Element {
  const categories = [...new Set(WIDGETS.map((w) => w.category))];
  return (
    <div className="space-y-4">
      {categories.map((cat) => (
        <div key={cat}>
          <h3 className="text-sm font-medium text-text-secondary mb-2">{cat}</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-text-secondary">
                  <th className="py-1.5 px-3 font-medium">ID</th>
                  <th className="py-1.5 px-3 font-medium">Name</th>
                  <th className="py-1.5 px-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {WIDGETS.filter((w) => w.category === cat).map((w) => (
                  <tr key={w.id} className="border-b border-border/50 hover:bg-surface-hover">
                    <td className="py-1.5 px-3 font-mono text-text-primary">{w.id}</td>
                    <td className="py-1.5 px-3 text-text-secondary">{w.name}</td>
                    <td className="py-1.5 px-3"><StatusBadge status={w.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}

function EndpointsPanel({ endpoints, loading, error }: {
  endpoints: EndpointInfo[];
  loading: boolean;
  error: string | null;
}): JSX.Element {
  if (loading) {
    return <p className="text-text-secondary text-sm p-4">Loading endpoint data...</p>;
  }
  if (error) {
    return (
      <div className="p-4 text-sm">
        <p className="text-red-400">Failed to load endpoints: {error}</p>
        <p className="text-text-muted mt-1">Ensure the FlintTrade backend is running (port 5100).</p>
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <div className="px-3 pb-3 text-xs text-text-muted">
        {endpoints.length} endpoints registered
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-text-secondary">
            <th className="py-2 px-3 font-medium">Method</th>
            <th className="py-2 px-3 font-medium">Path</th>
            <th className="py-2 px-3 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {endpoints.map((ep) => (
            <tr key={`${ep.method}-${ep.path}`} className="border-b border-border/50 hover:bg-surface-hover">
              <td className="py-2 px-3">
                <span className={`font-mono text-xs font-bold ${ep.method === "GET" ? "text-emerald-400" : ep.method === "POST" ? "text-amber-400" : "text-blue-400"}`}>
                  {ep.method}
                </span>
              </td>
              <td className="py-2 px-3 font-mono text-text-primary text-xs">{ep.path}</td>
              <td className="py-2 px-3"><StatusBadge status={ep.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FeaturesPanel(): JSX.Element {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-text-secondary">
            <th className="py-2 px-3 font-medium">Feature</th>
            <th className="py-2 px-3 font-medium">Status</th>
            <th className="py-2 px-3 font-medium">Route</th>
          </tr>
        </thead>
        <tbody>
          {FEATURES.map((f) => (
            <tr key={f.name} className="border-b border-border/50 hover:bg-surface-hover">
              <td className="py-2 px-3 text-text-primary">{f.name}</td>
              <td className="py-2 px-3"><StatusBadge status={f.status} /></td>
              <td className="py-2 px-3 font-mono text-text-secondary text-xs">{f.route}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AbsorptionPanel(): JSX.Element {
  const [data, setData] = useState<AbsorptionData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/ft-api/v1/admin/repos")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<AbsorptionData>;
      })
      .then(setData)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <p className="text-text-secondary text-sm p-4">Loading absorption data...</p>;
  }
  if (error) {
    return (
      <div className="p-4 text-sm">
        <p className="text-red-400">Failed to load absorption data: {error}</p>
        <p className="text-text-muted mt-1">Ensure the FlintTrade backend is running (port 5100).</p>
      </div>
    );
  }
  if (!data) return <></>;


  const repos = Object.entries(data.repos);
  const statusCounts: Record<string, number> = {};
  for (const [, info] of repos) {
    statusCounts[info.status] = (statusCounts[info.status] ?? 0) + 1;
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-3 flex-wrap px-3">
        {Object.entries(statusCounts).map(([s, count]) => (
          <div key={s} className="flex items-center gap-1.5">
            <StatusBadge status={s} />
            <span className="text-sm text-text-secondary font-mono">{count}</span>
          </div>
        ))}
        <span className="text-text-muted text-xs self-center ml-2">
          ({repos.length} tracked / {data.total_repos} declared)
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-text-secondary">
              <th className="py-2 px-3 font-medium">Repo</th>
              <th className="py-2 px-3 font-medium">Status</th>
              <th className="py-2 px-3 font-medium">Package</th>
              <th className="py-2 px-3 font-medium">Examined</th>
              <th className="py-2 px-3 font-medium">Notes</th>
            </tr>
          </thead>
          <tbody>
            {repos.sort(([a], [b]) => a.localeCompare(b)).map(([name, info]) => (
              <tr key={name} className="border-b border-border/50 hover:bg-surface-hover">
                <td className="py-1.5 px-3 font-mono text-text-primary text-xs">
                  {info.upstream_url ? (
                    <a href={info.upstream_url} target="_blank" rel="noopener noreferrer" className="hover:text-accent">
                      {name}
                    </a>
                  ) : name}
                </td>
                <td className="py-1.5 px-3"><StatusBadge status={info.status} /></td>
                <td className="py-1.5 px-3 text-text-secondary text-xs">{info.target_package}</td>
                <td className="py-1.5 px-3 text-text-muted text-xs font-mono">{info.last_examined ?? "never"}</td>
                <td className="py-1.5 px-3 text-text-muted text-xs max-w-xs truncate">{info.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DepsPanel(): JSX.Element {
  return (
    <pre className="text-xs font-mono text-text-secondary p-4 whitespace-pre overflow-auto glass-surface-l1 rounded-glass-inner">
      {DEPENDENCY_GRAPH}
    </pre>
  );
}

// ---------------------------------------------------------------------------
// Logs panel
// ---------------------------------------------------------------------------

type LogLevel = "ALL" | "ERROR" | "WARNING" | "INFO";

const LOG_LEVEL_COLOURS: Record<LogEntry["level"], string> = {
  ERROR:   "bg-red-500/20 text-red-400 border-red-500/30",
  WARNING: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  INFO:    "bg-blue-500/20 text-blue-400 border-blue-500/30",
  DEBUG:   "bg-zinc-500/20 text-zinc-400 border-zinc-500/30",
};

const MAX_ENTRIES = 100;
const POLL_INTERVAL_MS = 3_000;

function LogLevelBadge({ level }: { level: LogEntry["level"] }): JSX.Element {
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 text-xs font-mono font-semibold rounded border ${LOG_LEVEL_COLOURS[level]}`}>
      {level}
    </span>
  );
}

function LogsPanel(): JSX.Element {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [filter, setFilter] = useState<LogLevel>("ALL");
  const [search, setSearch] = useState("");
  const [backendAvailable, setBackendAvailable] = useState(true);
  const [wsConnected, setWsConnected] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const shouldAutoScroll = useRef(true);

  // Append new entries, capping at MAX_ENTRIES.
  const appendEntries = useCallback((incoming: LogEntry[]): void => {
    setEntries((prev) => {
      const merged = [...prev, ...incoming];
      return merged.length > MAX_ENTRIES ? merged.slice(-MAX_ENTRIES) : merged;
    });
  }, []);

  // WebSocket connection — primary path.
  useEffect(() => {
    const wsUrl = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ft-api/v1/logs/stream`;

    let ws: WebSocket;
    let retryTimeout: ReturnType<typeof setTimeout> | null = null;

    function connect(): void {
      try {
        ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = (): void => {
          setWsConnected(true);
          setBackendAvailable(true);
        };

        ws.onmessage = (event: MessageEvent): void => {
          const entry = safeParse(event.data as string, logEntrySchema);
          if (entry) appendEntries([entry]);
          // Malformed frames silently discarded
        };

        ws.onerror = (): void => {
          setWsConnected(false);
        };

        ws.onclose = (): void => {
          setWsConnected(false);
          wsRef.current = null;
          // Retry after 5 s if the component is still mounted.
          retryTimeout = setTimeout(connect, 5_000);
        };
      } catch {
        setWsConnected(false);
      }
    }

    connect();

    return (): void => {
      if (retryTimeout !== null) clearTimeout(retryTimeout);
      if (wsRef.current) {
        wsRef.current.onclose = null; // Prevent retry loop on unmount.
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [appendEntries]);

  // Polling fallback — used when WebSocket is not connected.
  useEffect(() => {
    if (wsConnected) return;

    let cancelled = false;

    async function poll(): Promise<void> {
      try {
        const res = await fetch("/ft-api/v1/logs/recent");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as { entries: LogEntry[] };
        if (!cancelled) {
          setBackendAvailable(true);
          setEntries(data.entries.slice(-MAX_ENTRIES));
        }
      } catch {
        if (!cancelled) setBackendAvailable(false);
      }
    }

    void poll();
    const id = setInterval(() => { void poll(); }, POLL_INTERVAL_MS);

    return (): void => {
      cancelled = true;
      clearInterval(id);
    };
  }, [wsConnected]);

  // Auto-scroll to bottom when entries change.
  useEffect(() => {
    if (!shouldAutoScroll.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries]);

  const handleScroll = (): void => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    shouldAutoScroll.current = atBottom;
  };

  const filtered = entries.filter((e) => {
    if (filter !== "ALL" && e.level !== filter) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      return (
        e.message.toLowerCase().includes(q) ||
        (e.request_id?.toLowerCase().includes(q) ?? false)
      );
    }
    return true;
  });

  const FILTER_LEVELS: LogLevel[] = ["ALL", "ERROR", "WARNING", "INFO"];

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        {/* Level filter buttons */}
        <div role="group" aria-label="Log level filter" className="flex items-center gap-1">
          {FILTER_LEVELS.map((lvl) => (
            <button
              key={lvl}
              type="button"
              onClick={() => setFilter(lvl)}
              aria-pressed={filter === lvl}
              className={`px-2.5 py-1 text-xs font-medium rounded border transition-colors ${
                filter === lvl
                  ? "bg-accent/20 text-accent border-accent/40"
                  : "bg-surface-elevated text-text-secondary border-border hover:text-text-primary hover:border-border-default"
              }`}
            >
              {lvl}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="relative flex-1 min-w-40 max-w-72">
          <input
            type="search"
            placeholder="Search logs…"
            aria-label="Search logs"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full h-7 pl-2.5 pr-7 text-xs rounded border border-border bg-surface-elevated text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch("")}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
              aria-label="Clear search"
            >
              <X className="w-3 h-3" />
            </button>
          )}
        </div>

        {/* Status indicator */}
        <span className="ml-auto flex items-center gap-1.5 text-xs text-text-muted">
          <span className={`w-1.5 h-1.5 rounded-full ${wsConnected ? "bg-emerald-400" : backendAvailable ? "bg-amber-400" : "bg-red-400"}`} />
          {wsConnected ? "Live" : backendAvailable ? "Polling" : "Unavailable"}
        </span>

        {/* Entry count */}
        <span className="text-xs font-mono text-text-muted">
          {filtered.length}/{entries.length}
        </span>
      </div>

      {/* Log container */}
      {!backendAvailable && entries.length === 0 ? (
        <div className="rounded-glass-inner border border-glass-l2 bg-glass-l1 p-6 text-center text-sm text-text-muted">
          Backend unavailable. Ensure the FlintTrade backend is running on port 5100.
        </div>
      ) : (
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="h-130 overflow-y-auto rounded-glass-inner border border-glass-l2 bg-glass-l1 font-mono text-xs"
          role="log"
          aria-live="polite"
          aria-label="Live log viewer"
        >
          {filtered.length === 0 ? (
            <p className="p-4 text-text-muted text-center">No log entries match the current filter.</p>
          ) : (
            <table className="w-full border-collapse">
              <thead className="sticky top-0 bg-surface-elevated z-10">
                <tr className="border-b border-border text-left text-text-secondary">
                  <th className="py-1.5 px-3 font-medium w-36">Timestamp</th>
                  <th className="py-1.5 px-3 font-medium w-24">Level</th>
                  <th className="py-1.5 px-3 font-medium">Message</th>
                  <th className="py-1.5 px-3 font-medium w-28">Request ID</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((entry, idx) => (
                  <tr
                    key={`${entry.timestamp}-${idx}`}
                    className="border-b border-border/40 hover:bg-surface-hover align-top"
                  >
                    <td className="py-1 px-3 text-text-muted whitespace-nowrap">
                      {entry.timestamp.length > 19
                        ? entry.timestamp.slice(11, 19)
                        : entry.timestamp}
                    </td>
                    <td className="py-1 px-3">
                      <LogLevelBadge level={entry.level} />
                    </td>
                    <td className="py-1 px-3 text-text-primary break-all">{entry.message}</td>
                    <td className="py-1 px-3 text-text-muted truncate max-w-28">
                      {entry.request_id ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main AdminRoute component
// ---------------------------------------------------------------------------

export default function AdminRoute(): JSX.Element {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<TabId>("system");
  const { data: introspect, loading: introLoading, error: introError } = useIntrospect();

  const packages = introspect?.packages ?? [];
  const endpoints = introspect?.endpoints ?? [];

  const renderPanel = (): JSX.Element => {
    switch (activeTab) {
      case "system":
        return <SystemMetricsPanel />;
      case "packages":
        return <PackagesPanel packages={packages} loading={introLoading} error={introError} />;
      case "widgets":
        return <WidgetsPanel />;
      case "endpoints":
        return <EndpointsPanel endpoints={endpoints} loading={introLoading} error={introError} />;
      case "features":
        return <FeaturesPanel />;
      case "absorption":
        return <AbsorptionPanel />;
      case "deps":
        return <DepsPanel />;
      case "logs":
        return <LogsPanel />;
    }
  };

  return (
    <div className="min-h-screen bg-background text-text-primary">
      {/* Header */}
      <header className="sticky top-0 z-10 bg-glass-chrome backdrop-blur-md border-b border-glass-chrome">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-3">
          <button
            onClick={() => navigate(-1)}
            className="p-1.5 rounded hover:bg-surface-hover transition-colors"
            aria-label="Go back"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <h1 className="text-lg font-semibold">Admin Dashboard</h1>
            <p className="text-xs text-text-muted">DEV only &mdash; not visible in production</p>
          </div>
          <span className="ml-auto text-xs font-mono text-amber-400 bg-amber-500/10 px-2 py-1 rounded border border-amber-500/20">
            DEV
          </span>
        </div>
      </header>

      {/* Tab bar */}
      <nav className="bg-glass-l2 backdrop-blur-sm border-b border-glass-l1" role="tablist" aria-label="Admin sections">
        <div className="max-w-7xl mx-auto px-4 flex gap-1 overflow-x-auto">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                role="tab"
                aria-selected={isActive}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-3 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                  isActive
                    ? "border-accent text-accent"
                    : "border-transparent text-text-secondary hover:text-text-primary hover:border-border"
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {tab.label}
              </button>
            );
          })}
        </div>
      </nav>

      {/* Content */}
      <main aria-label="Admin Dashboard" className="max-w-7xl mx-auto px-4 py-6">
        {renderPanel()}
      </main>
    </div>
  );
}
