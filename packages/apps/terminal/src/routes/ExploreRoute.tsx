/**
 * ExploreRoute — demo/preview page at /explore.
 *
 * Shows all 6 FlintTrade modules with hardcoded sample data.
 * No broker connection required. Every module card navigates to the
 * actual route and shows a contextual toast prompting the user to connect
 * a broker gateway for live data.
 */

import { useState, useCallback, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { motion } from "framer-motion";
import {
  CandlestickChart,
  PiggyBank,
  BookOpen,
  Zap,
  Workflow,
  Bot,
  TrendingUp,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  CircleDot,
  CheckCircle2,
  X,
  Info,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import PublicRouteShell from "@/components/layout/PublicRouteShell";
import { GlassCard } from "@/components/ui/GlassCard";
import { motionConfig } from "@/lib/motion";
import SpotlightTour from "@/components/demo/ExploreTour";
import type { TourStep } from "@/components/demo/ExploreTour";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";

// Aceternity UI
import { HoverCard } from "@/components/aceternity/card-hover-effect";

// ---------------------------------------------------------------------------
// Toast — inline, no external library needed
// ---------------------------------------------------------------------------

interface ToastState {
  visible: boolean;
  message: string;
}

function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  return (
    <motion.div
      role="status"
      aria-live="polite"
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-4 py-3 rounded-lg bg-surface-elevated border border-border-default shadow-xl text-sm text-text-primary"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 8 }}
      transition={motionConfig.transitions.fade}
    >
      <Info className="w-4 h-4 text-primary shrink-0" />
      <span>{message}</span>
      <button
        onClick={onClose}
        className="ml-2 text-text-muted hover:text-text-primary transition-colors cursor-pointer"
        aria-label="Dismiss"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Mini chart — CSS bar visualisation, no dependencies
// ---------------------------------------------------------------------------

const TRADE_BARS = [42, 55, 38, 62, 71, 58, 65, 80, 73, 88, 76, 92];
const LAB_BARS   = [28, 35, 42, 38, 55, 60, 52, 68, 74, 70, 82, 90];

function MiniChart({
  bars,
  color,
}: {
  bars: number[];
  color: "profit" | "purple";
}) {
  const colorClass =
    color === "profit"
      ? "bg-profit/70"
      : "bg-purple-500/70";
  const max = Math.max(...bars);
  return (
    <div className="flex items-end gap-0.5 h-8">
      {bars.map((v, i) => (
        <div
          key={i}
          className={`flex-1 rounded-sm ${colorClass}`}
          style={{ height: `${(v / max) * 100}%` }}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sample data (all hardcoded — intentional for demo)
// ---------------------------------------------------------------------------

interface Position {
  symbol: string;
  type: "CE" | "PE" | "EQ";
  qty: number;
  pnl: number;
  pnlPct: number;
}

interface Holding {
  symbol: string;
  invested: number;
  current: number;
  returnPct: number;
}

interface Course {
  title: string;
  topic: string;
  progress: number;
}

const SAMPLE_POSITIONS: Position[] = [
  { symbol: "NIFTY 24000 CE", type: "CE", qty: 50,  pnl:  3_250, pnlPct: 8.2  },
  { symbol: "BNKN 51500 PE",  type: "PE", qty: 15,  pnl: -1_080, pnlPct: -3.4 },
  { symbol: "RELIANCE",       type: "EQ", qty: 10,  pnl:  1_520, pnlPct: 5.1  },
];

const SAMPLE_HOLDINGS: Holding[] = [
  { symbol: "HDFC Bank",  invested: 5_00_000, current: 6_12_300, returnPct: 22.5 },
  { symbol: "Infosys",    invested: 3_00_000, current: 3_78_150, returnPct: 26.1 },
  { symbol: "Axis MF G",  invested: 2_50_000, current: 3_10_250, returnPct: 24.1 },
];

const SAMPLE_COURSES: Course[] = [
  { title: "Options Basics",       topic: "F&O",      progress: 75 },
  { title: "Understanding Greeks", topic: "Advanced", progress: 40 },
];

// ---------------------------------------------------------------------------
// Card previews — one per module
// ---------------------------------------------------------------------------

function TradePreview() {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-xs text-text-muted">
        <span>Portfolio Value</span>
        <span className="font-mono text-text-primary font-semibold">
          ₹10,00,000
        </span>
      </div>
      <div className="space-y-1.5">
        {SAMPLE_POSITIONS.map((p) => (
          <div
            key={p.symbol}
            className="flex items-center justify-between rounded-md bg-surface-base px-2.5 py-1.5 text-xs"
          >
            <div className="flex items-center gap-1.5 min-w-0">
              <span
                className={`text-xxs font-mono shrink-0 px-1 py-0.5 rounded ${
                  p.type === "CE"
                    ? "bg-bullish-bg text-bullish-text"
                    : p.type === "PE"
                      ? "bg-bearish-bg text-bearish-text"
                      : "bg-neutral-bg text-neutral-text"
                }`}
              >
                {p.type}
              </span>
              <span className="text-text-secondary truncate">{p.symbol}</span>
            </div>
            <span
              className={`font-mono font-semibold shrink-0 ${
                p.pnl >= 0 ? "text-profit" : "text-loss"
              }`}
            >
              {p.pnl >= 0 ? "+" : ""}
              {p.pnl.toLocaleString("en-IN")}
            </span>
          </div>
        ))}
      </div>
      <MiniChart bars={TRADE_BARS} color="profit" />
    </div>
  );
}

function InvestPreview() {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-xs text-text-muted">
        <span>Net Worth</span>
        <span className="font-mono text-text-primary font-semibold">
          ₹25,00,000
        </span>
      </div>
      <div className="space-y-1.5">
        {SAMPLE_HOLDINGS.map((h) => (
          <div
            key={h.symbol}
            className="flex items-center justify-between rounded-md bg-surface-base px-2.5 py-1.5 text-xs"
          >
            <span className="text-text-secondary truncate">{h.symbol}</span>
            <div className="flex items-center gap-1.5 shrink-0">
              <ArrowUpRight className="w-3 h-3 text-profit" />
              <span className="font-mono font-semibold text-profit">
                +{h.returnPct}%
              </span>
            </div>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2 rounded-md bg-surface-base px-2.5 py-2 text-xs text-text-muted">
        <CircleDot className="w-3 h-3 text-primary shrink-0" />
        SIP active — 3 funds, ₹15,000/month
      </div>
    </div>
  );
}

function LearnPreview() {
  return (
    <div className="space-y-3">
      {SAMPLE_COURSES.map((c) => (
        <div key={c.title} className="space-y-1.5">
          <div className="flex items-center justify-between text-xs">
            <span className="text-text-primary font-medium">{c.title}</span>
            <Badge
              variant="outline"
              className="text-xxs px-1.5 py-0 border-border-default"
            >
              {c.topic}
            </Badge>
          </div>
          <div
            className="h-1.5 rounded-full bg-surface-base overflow-hidden"
            role="progressbar"
            aria-valuenow={c.progress}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`${c.title} progress`}
          >
            <div
              className="h-full rounded-full bg-primary transition-[width]"
              style={{ width: `${c.progress}%` }}
            />
          </div>
          <span className="text-xxs text-text-muted">{c.progress}% complete</span>
        </div>
      ))}
      <div className="text-xxs text-text-muted pt-1">
        + 12 more modules available
      </div>
    </div>
  );
}

function LabPreview() {
  return (
    <div className="space-y-3">
      <div className="rounded-md bg-surface-base px-2.5 py-2.5 text-xs space-y-1.5">
        <div className="text-text-primary font-medium">EMA Crossover Backtest</div>
        <div className="flex gap-4 text-xxs text-text-muted">
          <span>
            Sharpe{" "}
            <span className="font-mono text-profit font-semibold">1.85</span>
          </span>
          <span>
            Win Rate{" "}
            <span className="font-mono text-profit font-semibold">62%</span>
          </span>
          <span>
            Max DD{" "}
            <span className="font-mono text-loss font-semibold">-8.3%</span>
          </span>
        </div>
      </div>
      <MiniChart bars={LAB_BARS} color="purple" />
      <div className="text-xxs text-text-muted">
        Equity curve — 180-day simulation
      </div>
    </div>
  );
}

function AutomatePreview() {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between rounded-md bg-surface-base px-2.5 py-2.5 text-xs">
        <div>
          <div className="text-text-primary font-medium">Pre-Market Scanner</div>
          <div className="text-xxs text-text-muted">Runs at 09:00 IST daily</div>
        </div>
        <Badge className="bg-profit/15 text-profit text-xxs border-0">
          Active
        </Badge>
      </div>
      <div className="flex items-center justify-between rounded-md bg-surface-base px-2.5 py-2.5 text-xs">
        <div>
          <div className="text-text-primary font-medium">TradingView Webhook</div>
          <div className="text-xxs text-text-muted">54-node flow builder</div>
        </div>
        <Badge className="bg-neutral-bg text-neutral-text text-xxs border-0">
          Ready
        </Badge>
      </div>
      <div className="flex items-center gap-2 rounded-md bg-surface-base px-2.5 py-2 text-xs">
        <CheckCircle2 className="w-3 h-3 text-profit shrink-0" />
        <span className="text-text-muted">Kill switch — armed</span>
      </div>
    </div>
  );
}

function AIPreview() {
  return (
    <div className="space-y-2">
      <div className="rounded-md bg-surface-base px-2.5 py-2.5 text-xs space-y-1">
        <div className="text-xxs text-text-muted">You</div>
        <div className="text-text-secondary leading-relaxed">
          What&apos;s the best options strategy for low VIX?
        </div>
      </div>
      <div className="rounded-md bg-primary/8 border border-primary/20 px-2.5 py-2.5 text-xs space-y-1">
        <div className="text-xxs text-primary">FlintAI</div>
        <div className="text-text-secondary leading-relaxed">
          In low volatility, selling premium strategies like Iron Condors tend to outperform...
        </div>
      </div>
      <div className="flex items-center justify-between rounded-md bg-surface-base px-2.5 py-2 text-xs">
        <span className="text-text-secondary">NIFTY Signal</span>
        <div className="flex items-center gap-1.5">
          <TrendingUp className="w-3 h-3 text-profit" />
          <span className="text-profit font-semibold">BUY · 82%</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Module card definitions
// ---------------------------------------------------------------------------

interface ModuleDef {
  id: string;
  icon: LucideIcon;
  iconColor: string;
  title: string;
  subtitle: string;
  route: string;
  preview: React.ReactNode;
}

const MODULES: ModuleDef[] = [
  {
    id: "trade",
    icon: CandlestickChart,
    iconColor: "text-amber-400",
    title: "Trade",
    subtitle: "F&O scalping, options analysis, real-time execution",
    route: "/trade",
    preview: <TradePreview />,
  },
  {
    id: "invest",
    icon: PiggyBank,
    iconColor: "text-emerald-400",
    title: "Invest",
    subtitle: "Mutual funds, SIPs, portfolio tracking, net worth",
    route: "/invest",
    preview: <InvestPreview />,
  },
  {
    id: "learn",
    icon: BookOpen,
    iconColor: "text-blue-400",
    title: "Learn",
    subtitle: "Market basics to advanced strategies — built in",
    route: "/learn",
    preview: <LearnPreview />,
  },
  {
    id: "lab",
    icon: Zap,
    iconColor: "text-purple-400",
    title: "Strategy Lab",
    subtitle: "Rust-powered tick-level backtesting",
    route: "/lab",
    preview: <LabPreview />,
  },
  {
    id: "automate",
    icon: Workflow,
    iconColor: "text-rose-400",
    title: "Automate",
    subtitle: "Flow builder, cron scheduler, Telegram kill switch",
    route: "/automate",
    preview: <AutomatePreview />,
  },
  {
    id: "ai",
    icon: Bot,
    iconColor: "text-cyan-400",
    title: "AI",
    subtitle: "Local LLM advisor, RAG analysis, sentiment signals",
    route: "/ai",
    preview: <AIPreview />,
  },
];

// ---------------------------------------------------------------------------
// Stat definitions — numeric value + label
// ---------------------------------------------------------------------------

interface StatDef {
  label: string;
  value: number;
  suffix: string;
}

const STATS: StatDef[] = [
  { label: "Brokers supported", value: 30,  suffix: "+" },
  { label: "Modules",           value: 6,   suffix: ""  },
  { label: "Strategies",        value: 101, suffix: "+" },
  { label: "Indicators",        value: 150, suffix: "+" },
];

// ---------------------------------------------------------------------------
// Module preview card — Framer Motion stagger + whileHover scale + glow
// ---------------------------------------------------------------------------

interface ModuleCardProps {
  module: ModuleDef;
  index: number;
  onNavigate: (route: string, title: string) => void;
}

function ModuleCard({ module, index, onNavigate }: ModuleCardProps) {
  const Icon = module.icon;
  return (
    // Staggered slide-up entrance — consistent with motionConfig throughout the app
    <motion.div
      variants={motionConfig.variants.slideUp}
      initial="initial"
      animate="animate"
      transition={motionConfig.stagger(index)}
      // Scale + subtle shadow on hover
      whileHover={{ scale: 1.02 }}
      className="group relative"
      style={{ transformOrigin: "center" }}
    >
      <button
        type="button"
        onClick={() => onNavigate(module.route, module.title)}
        className="relative text-left w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 rounded-lg"
        aria-label={`Explore ${module.title} module`}
      >
        {/*
         * HoverCard: provides the cursor-tracking spotlight gradient.
         * The inner motion.div handles the border glow that expands on hover
         * via Tailwind group-hover utilities (accent color, shadow).
         */}
        <HoverCard
          className={[
            "h-full",
            "transition-shadow duration-200",
            "group-hover:shadow-lg group-hover:shadow-black/30",
            "group-hover:border-accent/40",
          ].join(" ")}
        >
          {/*
           * GlassCard as interior layout container.
           * glass={false} so it uses standard card surface tokens.
           * bg/border overridden to transparent — HoverCard already owns those.
           */}
          <GlassCard
            glass={false}
            className="bg-transparent border-0 rounded-lg p-5 h-full shadow-none gap-0"
          >
            {/* Preview badge */}
            <span className="absolute top-3 right-3 text-xxs font-medium px-1.5 py-0.5 rounded bg-surface-elevated text-text-muted border border-border-subtle">
              Preview
            </span>

            {/* Header */}
            <div className="flex items-center gap-2.5 mb-3">
              <div className="p-1.5 rounded-lg bg-surface-elevated">
                <Icon className={`w-4 h-4 ${module.iconColor}`} />
              </div>
              <div className="min-w-0">
                <h3 className="font-heading font-semibold text-sm text-text-primary leading-tight">
                  {module.title}
                </h3>
                <p className="text-xxs text-text-muted truncate">{module.subtitle}</p>
              </div>
            </div>

            {/* Module-specific preview */}
            <div className="mt-2">{module.preview}</div>

            {/* Footer hover cue */}
            <div className="mt-3 flex items-center gap-1 text-xxs text-text-disabled group-hover:text-text-muted transition-colors">
              <span>Open {module.title}</span>
              <ArrowRight className="w-3 h-3" />
            </div>
          </GlassCard>
        </HoverCard>
      </button>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Main route
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Explore tour steps — highlights key UI sections for beginners
// ---------------------------------------------------------------------------

const EXPLORE_TOUR_STEPS: TourStep[] = [
  {
    target: null,
    title: "Welcome to Explore Mode",
    description:
      "This is a fully interactive preview of FlintTrade using sample data. No broker connection is needed. Let us walk you through the key sections.",
    placement: "bottom",
  },
  {
    target: "[aria-label='Explore navigation']",
    title: "Navigation & Setup",
    description:
      "Use Settings to connect FlintTrade's broker gateway or an OpenAlgo-compatible server. When you're ready, click Get Started to run the setup wizard.",
    placement: "bottom",
  },
  {
    target: "#explore-main",
    title: "Module Cards",
    description:
      "Each card represents a full module — Trade, Invest, Learn, Lab, Automate, and AI. Click any card to open the module with sample data.",
    placement: "bottom",
  },
  {
    target: ".grid.grid-cols-1",
    title: "Six Modules",
    description:
      "FlintTrade serves three personas from one app: Trader (F&O scalping), Investor (MFs, SIPs, net worth), and Beginner (guided learning, paper trading).",
    placement: "top",
  },
  {
    target: ".rounded-lg.border.border-border-default.bg-surface-card",
    title: "Ready to Go Live?",
    description:
      "Set up FlintTrade's broker gateway, or connect an existing OpenAlgo-compatible server. Takes about 2 minutes.",
    placement: "top",
  },
];

export default function ExploreRoute() {
  const navigate = useNavigate();
  const [toast, setToast] = useState<ToastState>({ visible: false, message: "" });
  const [showTour, setShowTour] = useState(false);

  const dismissToast = useCallback(() => {
    setToast({ visible: false, message: "" });
  }, []);

  const handleNavigate = useCallback(
    (route: string, title: string) => {
      setToast({
        visible: true,
        message: `Opening ${title} - connect a broker gateway in Settings for live data.`,
      });
      setTimeout(() => {
        navigate(route);
      }, 800);
    },
    [navigate],
  );

  const startDemoMode = useCallback(() => {
    useModeStore.getState().setMode("explore");
    useAuthStore.getState().setLoggedIn("demo-user", "Explorer", "");
    navigate("/home");
  }, [navigate]);

  // Auto-dismiss toast after 4 s
  useEffect(() => {
    if (!toast.visible) return;
    const id = setTimeout(dismissToast, 4000);
    return () => clearTimeout(id);
  }, [toast.visible, dismissToast]);

  return (
    <>
      <PublicRouteShell
        mainLabel="Explore mode"
        eyebrow="Sample workspace"
        title="Explore FlintTrade"
        subtitle="Open every module with simulated data, then connect FlintTrade's broker gateway when you are ready for live data."
        actions={
          <nav aria-label="Explore navigation" className="flex items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-xs text-text-muted hover:text-text-primary"
              onClick={startDemoMode}
            >
              Demo Mode
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="hidden text-xs text-text-muted hover:text-text-primary sm:inline-flex"
              asChild
            >
              <Link to="/settings">Settings</Link>
            </Button>
            <Button
              type="button"
              size="sm"
              className="text-xs"
              onClick={() => navigate("/setup")}
            >
              Get Started
              <ArrowRight className="size-3.5" aria-hidden="true" />
            </Button>
          </nav>
        }
      >
        <div id="explore-main" className="mx-auto max-w-6xl space-y-8">
          <div className="mx-auto flex max-w-2xl items-start gap-2 rounded-xl border border-accent/30 bg-accent/10 px-4 py-3 text-left shadow-xl shadow-black/10 backdrop-blur-xl">
            <Info className="mt-0.5 size-4 shrink-0 text-accent" />
            <p className="text-xs leading-relaxed text-accent">
              <strong>Explore Mode</strong> - all data shown is sample only. Connect a broker in Settings to see live data.
            </p>
          </div>

          <section className="mx-auto grid max-w-4xl gap-5 border-b border-border-default/60 pb-6 text-center">
            <div className="mx-auto space-y-3">
              <div className="inline-flex items-center gap-2 rounded-full border border-border-default/70 bg-surface-card/60 px-3 py-1.5 text-xs text-text-muted shadow-lg shadow-black/10 backdrop-blur-xl">
                <BarChart3 className="size-3.5 text-primary" aria-hidden="true" />
                No broker connection needed
              </div>
              <p className="mx-auto max-w-2xl text-sm leading-relaxed text-text-secondary">
                The preview uses the same cards, controls, and route behaviour as the app so visual checks here match what users see after setup.
              </p>
            </div>
            <div className="mx-auto flex flex-col items-center justify-center gap-2 sm:flex-row">
              <Button
                type="button"
                size="sm"
                className="w-full sm:w-auto"
                onClick={startDemoMode}
              >
                Enter Demo Workspace
                <ArrowRight className="size-3.5" aria-hidden="true" />
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-full border-border-default text-text-primary hover:bg-surface-hover sm:w-auto"
                onClick={() => setShowTour(true)}
              >
                Start Guided Tour
              </Button>
            </div>
            <div className="mx-auto grid w-full max-w-2xl grid-cols-2 gap-3 sm:grid-cols-4">
              {STATS.map((stat) => (
                <div
                  key={stat.label}
                  className="rounded-xl border border-border-default/70 bg-surface-card/60 px-3 py-2 shadow-xl shadow-black/10 backdrop-blur-xl"
                >
                  <div className="font-heading text-lg font-bold text-text-primary">
                    {stat.value}{stat.suffix}
                  </div>
                  <div className="text-xxs text-text-muted">{stat.label}</div>
                </div>
              ))}
            </div>
          </section>

          <motion.div
            variants={motionConfig.variants.fadeIn}
            initial="initial"
            animate="animate"
          >
            <h2 className="mb-4 text-center font-heading text-xs font-semibold uppercase tracking-[0.28em] text-text-secondary">
              All Modules
            </h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {MODULES.map((mod, i) => (
                <ModuleCard
                  key={mod.id}
                  module={mod}
                  index={i}
                  onNavigate={handleNavigate}
                />
              ))}
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.3, ease: "easeOut", delay: 0.1 }}
          >
            <div className="rounded-xl border border-border-default/70 bg-surface-card/70 px-5 py-5 shadow-2xl shadow-black/20 backdrop-blur-xl">
              <div className="flex flex-col items-center gap-4 text-center">
                <div className="flex flex-col items-center gap-3">
                  <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-profit/10 text-profit">
                    <TrendingUp className="size-4" aria-hidden="true" />
                  </div>
                  <div>
                    <h2 className="font-heading text-base font-semibold text-text-primary">
                      Ready to start?
                    </h2>
                    <p className="mt-1 text-sm text-text-muted">
                      Set up your workspace in 2 minutes, then connect FlintTrade's broker gateway or an OpenAlgo-compatible server.
                    </p>
                  </div>
                </div>
                <div className="flex flex-col gap-3 sm:flex-row">
                  <Button
                    type="button"
                    onClick={() => navigate("/setup")}
                    className="sm:min-w-44"
                  >
                    Set Up Workspace
                    <ArrowRight className="size-4" aria-hidden="true" />
                  </Button>
                  <Button
                    variant="outline"
                    className="border-border-default text-text-primary hover:bg-surface-hover sm:min-w-44"
                    asChild
                  >
                    <Link to="/settings">
                      Connect Gateway
                    </Link>
                  </Button>
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </PublicRouteShell>

      {toast.visible && (
        <Toast message={toast.message} onClose={dismissToast} />
      )}

      {showTour && (
        <SpotlightTour
          steps={EXPLORE_TOUR_STEPS}
          onComplete={() => setShowTour(false)}
        />
      )}
    </>
  );
}
