/**
 * ExploreRoute — demo/preview page at /explore.
 *
 * Shows all 6 FlintTrade modules with hardcoded sample data.
 * No broker connection required. Every module card navigates to the
 * actual route and shows a contextual toast prompting the user to
 * connect OpenAlgo for live data.
 */

import { useState, useCallback, useEffect, useMemo } from "react";
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
import { LogoIcon } from "@/components/brand/Logo";
import { GlassCard } from "@/components/ui/GlassCard";
import { motionConfig } from "@/lib/motion";
import { useThemeStore } from "@/stores/themeStore";
import DemoChoice, { hasMadeDemoChoice } from "@/components/demo/DemoChoice";
import type { DemoChoiceValue } from "@/components/demo/DemoChoice";

// Magic UI
import { Particles } from "@/components/magicui/particles";
import { AnimatedCounter } from "@/components/magicui/animated-counter";
import { ShimmerButton } from "@/components/magicui/shimmer-button";

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
          <div className="h-1.5 rounded-full bg-surface-base overflow-hidden">
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
        className="relative text-left w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 rounded-xl"
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
            className="bg-transparent border-0 rounded-xl p-5 h-full shadow-none gap-0"
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

export default function ExploreRoute() {
  const navigate = useNavigate();
  const [toast, setToast] = useState<ToastState>({ visible: false, message: "" });
  const [showDemoChoice, setShowDemoChoice] = useState(() => !hasMadeDemoChoice());
  const theme = useThemeStore((s) => s.activeThemeId);

  // Read primary particle color from CSS vars — reactive to theme changes
  const particlePrimary = useMemo(() => {
    if (typeof window === "undefined") return "#22c55e";
    return (
      getComputedStyle(document.documentElement).getPropertyValue("--particle-primary").trim() ||
      "#22c55e"
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);

  const dismissToast = useCallback(() => {
    setToast({ visible: false, message: "" });
  }, []);

  const handleNavigate = useCallback(
    (route: string, title: string) => {
      setToast({
        visible: true,
        message: `Opening ${title} — connect OpenAlgo in Settings for live data.`,
      });
      setTimeout(() => {
        navigate(route);
      }, 800);
    },
    [navigate],
  );

  // Auto-dismiss toast after 4 s
  useEffect(() => {
    if (!toast.visible) return;
    const id = setTimeout(dismissToast, 4000);
    return () => clearTimeout(id);
  }, [toast.visible, dismissToast]);

  function handleDemoChoice(choice: DemoChoiceValue) {
    setShowDemoChoice(false);
    if (choice === "tour") {
      // TODO: Trigger SpotlightTour for explore-beginner tour definition
    }
    // "explore" choice = just dismiss the overlay, user explores freely
  }

  // Show DemoChoice overlay on first visit
  if (showDemoChoice) {
    return <DemoChoice onChoice={handleDemoChoice} />;
  }

  return (
    <>
      {/* Skip link for /explore — this route renders outside AppLayout so it
          needs its own skip navigation (Issue #63). Matches AppLayout's style. */}
      <a
        href="#explore-main"
        className="sr-only focus:not-sr-only focus:fixed focus:z-[200] focus:top-2 focus:left-2 focus:bg-accent focus:text-white focus:px-4 focus:py-2 focus:rounded-lg focus:text-sm focus:font-medium focus:shadow-lg"
      >
        Skip to main content
      </a>
      <div className="fixed inset-0 bg-surface-base overflow-y-auto">
        {/* ------------------------------------------------------------------ */}
        {/* Top bar                                                              */}
        {/* ------------------------------------------------------------------ */}
        <header className="sticky top-0 z-40 border-b border-border-subtle bg-surface-base/90 backdrop-blur-sm">
          <div className="max-w-6xl mx-auto px-6 h-12 flex items-center justify-between">
            <Link
              to="/welcome"
              className="flex items-center gap-2 text-text-secondary hover:text-text-primary transition-colors"
            >
              <LogoIcon size={20} />
              <span className="font-heading font-semibold text-sm">FlintTrade</span>
            </Link>
            <nav aria-label="Explore navigation" className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                className="text-xs text-text-muted hover:text-text-primary"
                asChild
              >
                <Link to="/settings">Settings</Link>
              </Button>
              {/* ShimmerButton wrapping the Get Started navigation */}
              <ShimmerButton
                onClick={() => navigate("/setup")}
                className="text-xs px-4 py-1.5"
              >
                Get Started
                <ArrowRight className="w-3.5 h-3.5" />
              </ShimmerButton>
            </nav>
          </div>
        </header>

        {/* Explore mode banner — persistent, below the sticky header */}
        <div className="bg-accent/10 border border-accent/30 rounded-lg px-4 py-2 mx-4 mt-2 flex items-center gap-2">
          <Info className="w-4 h-4 text-accent shrink-0" />
          <p className="text-xs text-accent">
            <strong>Explore Mode</strong> — All data shown is sample only. Connect a broker in Settings to see live data.
          </p>
        </div>

        <main id="explore-main" aria-label="Explore mode" className="max-w-6xl mx-auto px-6 py-12 space-y-12">
          {/* ---------------------------------------------------------------- */}
          {/* Hero — Particles background + heading                            */}
          {/* ---------------------------------------------------------------- */}
          <div className="relative text-center space-y-4 py-8 overflow-hidden rounded-2xl animate-fade-in">
              {/* Particles layer — behind everything */}
              <Particles
                quantity={40}
                color={particlePrimary}
                size={1.5}
                className="rounded-2xl"
              />

              <div className="relative z-10 space-y-4">
                <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface-card border border-border-default text-xs text-text-muted">
                  <BarChart3 className="w-3.5 h-3.5 text-primary" />
                  Sample data only — no broker connection needed
                </div>

                <h1
                  className="font-heading font-bold text-text-primary tracking-tight"
                  style={{ fontSize: "clamp(1.75rem, 4vw, 2.75rem)" }}
                >
                  Explore FlintTrade
                </h1>

                <p
                  className="text-text-secondary max-w-xl mx-auto leading-relaxed"
                  style={{ fontSize: "clamp(0.875rem, 1.5vw, 1rem)" }}
                >
                  See what&apos;s possible — no broker connection needed. Click any module to open it,
                  then connect OpenAlgo in Settings for live data.
                </p>

                {/* Stats row — AnimatedCounter for each number */}
                <div className="flex flex-wrap justify-center gap-6 pt-2">
                  {STATS.map((stat) => (
                    <div key={stat.label} className="text-center">
                      <div className="font-heading font-bold text-text-primary text-lg">
                        <AnimatedCounter
                          value={stat.value}
                          duration={1.5}
                          formatter={(v) => `${v}${stat.suffix}`}
                        />
                      </div>
                      <div className="text-xxs text-text-muted">{stat.label}</div>
                    </div>
                  ))}
                </div>
              </div>
          </div>

          {/* ---------------------------------------------------------------- */}
          {/* Module grid — motion.div fade-in wrapper, cards stagger inside   */}
          {/* ---------------------------------------------------------------- */}
          <motion.div
            variants={motionConfig.variants.fadeIn}
            initial="initial"
            animate="animate"
          >
            <h2 className="font-heading font-semibold text-text-secondary text-xs uppercase tracking-widest mb-5">
              All Modules
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
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

          {/* ---------------------------------------------------------------- */}
          {/* Bottom CTA — smooth opacity fade, matches welcome screen style   */}
          {/* ---------------------------------------------------------------- */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 1, ease: "easeOut", delay: 0.4 }}
          >
            <div className="rounded-xl border border-border-default bg-surface-card px-8 py-8 text-center space-y-4">
              <TrendingUp className="w-8 h-8 text-profit mx-auto" />
              <div>
                <h2 className="font-heading font-bold text-text-primary text-lg">
                  Ready to start?
                </h2>
                <p className="text-text-muted text-sm mt-1">
                  Set up your workspace in 2 minutes — or connect an existing OpenAlgo instance.
                </p>
              </div>
              <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-1">
                <ShimmerButton
                  onClick={() => navigate("/setup")}
                  shimmerColor="#22c55e"
                  className="px-8 py-3 text-base font-semibold bg-profit/10 border-profit/40 text-profit hover:bg-profit/15"
                >
                  Set Up Workspace
                  <ArrowRight className="w-4 h-4" />
                </ShimmerButton>
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 1, ease: "easeOut", delay: 0.7 }}
                >
                  <Button
                    variant="outline"
                    size="lg"
                    className="border-border-default text-text-primary hover:bg-surface-hover px-8"
                    asChild
                  >
                    <Link to="/settings">
                      Already have OpenAlgo?
                    </Link>
                  </Button>
                </motion.div>
              </div>
            </div>
          </motion.div>

          {/* Bottom spacer */}
          <div className="h-8" />
        </main>
      </div>

      {/* Toast — smooth opacity fade, no popup effect */}
      {toast.visible && (
        <Toast message={toast.message} onClose={dismissToast} />
      )}
    </>
  );
}
