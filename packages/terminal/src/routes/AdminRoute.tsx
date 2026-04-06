/**
 * AdminRoute — dev-only /admin dashboard.
 *
 * Only accessible when `import.meta.env.DEV` is true.
 * Provides internal visibility into package health, widget registry,
 * endpoint status, feature flags, absorption tracker, and dependencies.
 */

import { useState, useEffect, type JSX } from "react";
import { ArrowLeft, Package, LayoutGrid, Globe, Flag, GitBranch, Network } from "lucide-react";
import { useNavigate } from "react-router-dom";

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

// ---------------------------------------------------------------------------
// Tab IDs
// ---------------------------------------------------------------------------

type TabId = "packages" | "widgets" | "endpoints" | "features" | "absorption" | "deps";

const TABS: { id: TabId; label: string; icon: typeof Package }[] = [
  { id: "packages", label: "Packages", icon: Package },
  { id: "widgets", label: "Widgets", icon: LayoutGrid },
  { id: "endpoints", label: "Endpoints", icon: Globe },
  { id: "features", label: "Features", icon: Flag },
  { id: "absorption", label: "Absorption", icon: GitBranch },
  { id: "deps", label: "Dependencies", icon: Network },
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

function useIntrospect(): { data: IntrospectData | null; loading: boolean; error: string | null } {
  const [data, setData] = useState<IntrospectData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
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
  { id: "gex", name: "GEX Dashboard", category: "Analysis", status: "live" },
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
  { name: "GEX Dashboard", status: "live", route: "/trade" },
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
  +-- ft-api -------> core/app.py (port 5001)

core
  +-- openalgo_client -> OpenAlgo REST API
  +-- config ----------> .env + workspace.json
  +-- security --------> rate limiting, threat detection
  +-- monitoring ------> health, traffic, latency

gateway
  +-- core (config, models)
  +-- broker SDKs (30+ brokers via adapter.py)

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
        <p className="text-text-muted mt-1">Ensure the FlintTrade backend is running (port 5001).</p>
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
        <p className="text-text-muted mt-1">Ensure the FlintTrade backend is running (port 5001).</p>
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
        <p className="text-text-muted mt-1">Ensure the FlintTrade backend is running (port 5001).</p>
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
    <pre className="text-xs font-mono text-text-secondary p-4 whitespace-pre overflow-auto bg-surface-card rounded">
      {DEPENDENCY_GRAPH}
    </pre>
  );
}

// ---------------------------------------------------------------------------
// Main AdminRoute component
// ---------------------------------------------------------------------------

export default function AdminRoute(): JSX.Element {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<TabId>("packages");
  const { data: introspect, loading: introLoading, error: introError } = useIntrospect();

  const packages = introspect?.packages ?? [];
  const endpoints = introspect?.endpoints ?? [];

  const renderPanel = (): JSX.Element => {
    switch (activeTab) {
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
    }
  };

  return (
    <div className="min-h-screen bg-background text-text-primary">
      {/* Header */}
      <header className="sticky top-0 z-10 bg-surface-base border-b border-border">
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
      <nav className="bg-surface-base border-b border-border" role="tablist" aria-label="Admin sections">
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
