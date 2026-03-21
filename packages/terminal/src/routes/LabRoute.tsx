import { useState } from "react";
import {
  Zap,
  FlaskConical,
  PlayCircle,
  Settings2,
  TrendingUp,
  BarChart3,
  ChevronRight,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";

// ---------------------------------------------------------------------------
// Section registry
// ---------------------------------------------------------------------------

type SectionId = "backtest" | "forward-test" | "optimize" | "results" | "settings";

interface SectionDef {
  id: SectionId;
  label: string;
  icon: typeof FlaskConical;
  desc: string;
}

const SECTIONS: SectionDef[] = [
  { id: "backtest", label: "Backtest", icon: FlaskConical, desc: "Test strategies on historical data" },
  { id: "forward-test", label: "Forward Test", icon: PlayCircle, desc: "Paper trade strategies in live market" },
  { id: "optimize", label: "Optimize", icon: TrendingUp, desc: "Walk-forward optimization" },
  { id: "results", label: "Results", icon: BarChart3, desc: "Performance metrics & comparison" },
  { id: "settings", label: "Lab Settings", icon: Settings2, desc: "Module-specific configuration" },
];

// ---------------------------------------------------------------------------
// Section content components
// ---------------------------------------------------------------------------

function BacktestSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Backtest Engine
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Test your strategies against historical OHLCV data powered by the Rust tick-level
          backtesting engine. Supports 12 built-in strategies with walk-forward validation,
          Monte Carlo simulation, and comprehensive metrics (Sharpe, Sortino, max drawdown).
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <p className="text-xs text-text-muted mb-1">Built-in Strategies</p>
            <p className="text-2xl font-mono font-bold text-text-primary">12</p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <p className="text-xs text-text-muted mb-1">Metrics Computed</p>
            <p className="text-2xl font-mono font-bold text-text-primary">15+</p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <p className="text-xs text-text-muted mb-1">Engine</p>
            <p className="text-2xl font-mono font-bold text-accent">Rust/PyO3</p>
          </div>
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-sm text-text-primary mb-2">
          How It Works
        </h3>
        <ol className="space-y-2 text-sm text-text-secondary list-decimal list-inside">
          <li>Select a strategy from the built-in library or write your own</li>
          <li>Choose instrument, timeframe, and date range</li>
          <li>Run backtest against DuckDB historical data</li>
          <li>Review equity curve, trade log, and risk metrics</li>
          <li>Iterate on parameters and compare runs</li>
        </ol>
      </Card>
    </div>
  );
}

function ForwardTestSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Forward Testing
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Test strategies against live market data without risking real money. Forward testing
          connects to real-time WebSocket feeds and executes your strategy logic in paper mode,
          tracking virtual P&L, fills, and slippage in real-time.
        </p>
        <div className="bg-surface-base border border-border-default rounded-lg p-4">
          <h4 className="text-sm font-semibold text-text-primary mb-2">Key Features</h4>
          <ul className="space-y-1.5 text-sm text-text-secondary">
            <li className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
              Real-time market data via WebSocket (LTP/Quote/Depth)
            </li>
            <li className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
              Virtual order execution with simulated slippage
            </li>
            <li className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
              Live P&L tracking and position management
            </li>
            <li className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
              Side-by-side comparison with backtest results
            </li>
          </ul>
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <Badge className="bg-amber-500/20 text-amber-400 text-xs">Coming in v0.2.0</Badge>
        <p className="text-sm text-text-muted mt-2">
          Forward testing requires the strategy engine to be connected. This will be fully
          wired in the next release.
        </p>
      </Card>
    </div>
  );
}

function OptimizeSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Walk-Forward Optimization
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Optimize strategy parameters using walk-forward analysis to avoid overfitting.
          The optimizer splits historical data into in-sample (training) and out-of-sample
          (validation) windows, finding parameters that generalize across market regimes.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Methods</h4>
            <ul className="text-xs text-text-secondary space-y-1">
              <li>Grid Search</li>
              <li>Random Search</li>
              <li>Walk-Forward Windows</li>
              <li>Monte Carlo Validation</li>
            </ul>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Objective Functions</h4>
            <ul className="text-xs text-text-secondary space-y-1">
              <li>Maximize Sharpe Ratio</li>
              <li>Maximize Sortino Ratio</li>
              <li>Minimize Max Drawdown</li>
              <li>Maximize Profit Factor</li>
            </ul>
          </div>
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <Badge className="bg-amber-500/20 text-amber-400 text-xs">Coming in v0.2.0</Badge>
        <p className="text-sm text-text-muted mt-2">
          Parameter optimization UI will be available in the next release. The Python
          backtest-engine package already supports walk-forward optimization.
        </p>
      </Card>
    </div>
  );
}

function ResultsSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Performance Results
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Compare backtest runs side by side, view equity curves, drawdown analysis, and
          detailed trade logs. Export results to CSV or share with your team.
        </p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {["Sharpe Ratio", "Sortino Ratio", "Max Drawdown", "Win Rate", "Profit Factor", "Avg Trade", "Total Trades", "Expectancy"].map(
            (metric) => (
              <div
                key={metric}
                className="bg-surface-base border border-border-default rounded-lg p-3 text-center"
              >
                <p className="text-xs text-text-muted">{metric}</p>
                <p className="text-sm font-mono text-text-secondary mt-1">--</p>
              </div>
            ),
          )}
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <Badge className="bg-amber-500/20 text-amber-400 text-xs">Coming in v0.2.0</Badge>
        <p className="text-sm text-text-muted mt-2">
          Results dashboard will display live data once backtests are run. Run a backtest
          from the Backtest section to populate results here.
        </p>
      </Card>
    </div>
  );
}

function LabSettingsSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Lab Settings
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Configure module-specific settings for backtesting, forward testing, and optimization.
        </p>
        <div className="space-y-4">
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Default Instruments</h4>
            <p className="text-xs text-text-muted">
              Set default symbols for quick backtesting (e.g., NIFTY, BANKNIFTY, RELIANCE)
            </p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Data Range</h4>
            <p className="text-xs text-text-muted">
              Default lookback period for historical data (1M, 3M, 6M, 1Y, 3Y, 5Y)
            </p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Optimization Parameters</h4>
            <p className="text-xs text-text-muted">
              Default walk-forward window size, in-sample/out-of-sample split ratio, max iterations
            </p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Forward Test Defaults</h4>
            <p className="text-xs text-text-muted">
              Virtual capital, slippage model, commission assumptions
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

export default function LabRoute() {
  const [activeSection, setActiveSection] = useState<SectionId>("backtest");

  const sectionContent: Record<SectionId, React.ReactNode> = {
    "backtest": <BacktestSection />,
    "forward-test": <ForwardTestSection />,
    "optimize": <OptimizeSection />,
    "results": <ResultsSection />,
    "settings": <LabSettingsSection />,
  };

  return (
    <div className="h-full bg-surface-base flex flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-border-default bg-surface-card px-6 py-4">
        <div className="flex items-center gap-3">
          <Zap className="w-6 h-6 text-accent" />
          <div>
            <h1 className="font-heading font-bold text-lg text-text-primary">Strategy Lab</h1>
            <p className="text-xxs text-text-muted">
              Backtest, forward test, and optimize strategies — no broker has this built-in
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
