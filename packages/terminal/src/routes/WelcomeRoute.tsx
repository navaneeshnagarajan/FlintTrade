/**
 * WelcomeRoute — cinematic full-page welcome screen shown on first launch.
 *
 * Animation sequence (pure CSS @keyframes + React state):
 *   step 0 (0-1s):    Dark void — pure bg-surface-base
 *   step 1 (1-2s):    Green spark appears center, scales up with glow
 *   step 2 (2-3s):    Logo forms — LogoIcon + wordmark types out letter by letter
 *   step 3 (3-3.5s):  Tagline "Learn · Invest · Trade" fades in
 *   step 4 (3.5-6s):  6 pillar cards slide up from bottom, staggered 200ms each
 *   step 5 (6-7s):    CTA buttons fade in
 *
 * Skip (top-right) or Enter/Space/Escape jumps to step 5 immediately.
 */

import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  BookOpen,
  PiggyBank,
  CandlestickChart,
  Zap,
  Workflow,
  Bot,
  Moon,
  Circle,
  Leaf,
  Waves,
  Sun,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { LogoIcon } from "@/components/brand/Logo";
import { useSettingsStore } from "@/stores/settingsStore";

// Magic UI
import { Particles } from "@/components/magicui/particles";
import { BlurFade } from "@/components/magicui/blur-fade";
import { ShimmerButton } from "@/components/magicui/shimmer-button";

// Aceternity UI
import { Meteors } from "@/components/aceternity/meteors";
import { HoverCard } from "@/components/aceternity/card-hover-effect";

// ---------------------------------------------------------------------------
// Pillar data
// ---------------------------------------------------------------------------

interface Pillar {
  icon: LucideIcon;
  title: string;
  desc: string;
  color: string;
  route: string;
  preset: string;
}

const PILLARS: Pillar[] = [
  {
    icon: BookOpen,
    title: "Learn",
    desc: "Market basics to advanced strategies \u2014 built into the terminal",
    color: "text-blue-400",
    route: "/learn",
    preset: "learn-first",
  },
  {
    icon: PiggyBank,
    title: "Invest",
    desc: "Mutual funds, SIPs, portfolio tracking, net worth",
    color: "text-emerald-400",
    route: "/invest",
    preset: "invest-lite",
  },
  {
    icon: CandlestickChart,
    title: "Trade",
    desc: "F&O scalping, options analysis, real-time execution",
    color: "text-amber-400",
    route: "/trade",
    preset: "scalper-zone",
  },
  {
    icon: Zap,
    title: "Strategy Lab",
    desc: "Rust-powered tick-level backtesting \u2014 no broker has this",
    color: "text-purple-400",
    route: "/lab",
    preset: "analysis-desk",
  },
  {
    icon: Workflow,
    title: "Automate",
    desc: "54-node flow builder, cron scheduler, Telegram kill switch",
    color: "text-rose-400",
    route: "/automate",
    preset: "blank",
  },
  {
    icon: Bot,
    title: "AI",
    desc: "Local LLM advisor, RAG analysis, sentiment signals",
    color: "text-cyan-400",
    route: "/ai",
    preset: "minimal",
  },
];

// ---------------------------------------------------------------------------
// Theme options for the switcher
// ---------------------------------------------------------------------------

const THEME_OPTIONS = [
  { id: "midnight" as const, icon: Moon, label: "Midnight" },
  { id: "obsidian" as const, icon: Circle, label: "Obsidian" },
  { id: "terminal-green" as const, icon: Leaf, label: "Green" },
  { id: "ocean-blue" as const, icon: Waves, label: "Blue" },
  { id: "light" as const, icon: Sun, label: "Light" },
];

// ---------------------------------------------------------------------------
// Wordmark letters for typewriter effect
// ---------------------------------------------------------------------------

const WORDMARK = "FlintTrade";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function WelcomeRoute() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const theme = useSettingsStore((s) => s.theme);

  // Pillar click — set persona preference (don't navigate, let CTA handle it)
  const handlePillarClick = useCallback(
    (pillar: Pillar) => {
      const store = useSettingsStore.getState();
      store.setPersona(
        pillar.route === "/learn"
          ? "beginner"
          : pillar.route === "/invest"
            ? "investor"
            : "trader",
      );
      store.setInterests([pillar.title.toLowerCase()]);
      // Don't navigate — user picks their path via CTA buttons below
      setStep(5);
    },
    [],
  );

  // Skip handler — jump straight to CTAs
  const skipToEnd = useCallback(() => {
    setStep(5);
  }, []);

  // Keyboard shortcut: Enter, Space, or Escape to skip
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Enter" || e.key === " " || e.key === "Escape") {
        e.preventDefault();
        skipToEnd();
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [skipToEnd]);

  // Animation timeline — only advance if not already at or past the target step
  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];

    const schedule = (targetStep: number, delay: number) => {
      timers.push(
        setTimeout(() => {
          setStep((current) => (current < targetStep ? targetStep : current));
        }, delay),
      );
    };

    schedule(1, 1000); // spark
    schedule(2, 2000); // logo
    schedule(3, 3000); // tagline
    schedule(4, 3500); // pillar cards
    schedule(5, 6000); // CTA

    return () => timers.forEach(clearTimeout);
  }, []);

  return (
    <>
      {/* Inline CSS keyframes */}
      <style>{`
        @keyframes welcomeSparkGlow {
          0% { transform: scale(0); opacity: 0; }
          50% { transform: scale(1.5); opacity: 1; }
          100% { transform: scale(1); opacity: 1; }
        }

        @keyframes welcomeFadeInUp {
          from { transform: translateY(40px); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }

        @keyframes welcomeFadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        @keyframes welcomeTypeChar {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }

        .welcome-spark {
          will-change: transform, opacity;
          animation: welcomeSparkGlow 0.8s ease-out forwards;
        }

        .welcome-fade-in {
          will-change: opacity;
          animation: welcomeFadeIn 0.6s ease-out forwards;
        }

        .welcome-fade-in-up {
          will-change: transform, opacity;
          animation: welcomeFadeInUp 0.5s ease-out forwards;
        }

        .welcome-char {
          display: inline-block;
          opacity: 0;
          will-change: opacity, transform;
          animation: welcomeTypeChar 0.06s ease-out forwards;
        }

        .welcome-pillar-card {
          will-change: transform, opacity;
          opacity: 0;
          animation: welcomeFadeInUp 0.5s ease-out forwards;
        }
      `}</style>

      <div className="min-h-screen bg-surface-base flex flex-col items-center justify-center relative overflow-hidden select-none">
        {/* Particles — always visible, behind everything */}
        <Particles
          quantity={25}
          color="#22c55e"
          size={1.2}
          className="opacity-40"
        />

        {/* Meteors — visible during cinematic reveal (steps 1-4) */}
        {step >= 1 && step < 5 && (
          <Meteors number={10} />
        )}

        {/* Theme switcher — top-left */}
        <div className="fixed top-4 left-4 flex items-center gap-1 z-50">
          {THEME_OPTIONS.map((t) => {
            const ThemeIcon = t.icon;
            return (
              <button
                key={t.id}
                onClick={() => useSettingsStore.getState().setTheme(t.id)}
                className={`p-1.5 rounded transition-colors cursor-pointer ${
                  theme === t.id
                    ? "bg-accent/20 text-accent"
                    : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                }`}
                title={t.label}
              >
                <ThemeIcon size={14} />
              </button>
            );
          })}
        </div>

        {/* Skip button — always visible */}
        <button
          onClick={skipToEnd}
          className="absolute top-6 right-6 text-xs text-text-muted hover:text-text-primary cursor-pointer z-50 transition-colors duration-200"
        >
          Skip
        </button>

        {/* Main content container */}
        <div className="relative z-10 flex flex-col items-center gap-8 px-4 w-full max-w-5xl">
          {/* Step 1: Green spark */}
          {step >= 1 && (
            <div className="flex items-center justify-center">
              <div
                className="welcome-spark rounded-full"
                style={{
                  width: 16,
                  height: 16,
                  backgroundColor: "#22c55e",
                  boxShadow: "0 0 60px 20px rgba(34, 197, 94, 0.3)",
                }}
              />
            </div>
          )}

          {/* Step 2: Logo + Wordmark typewriter */}
          {step >= 2 && (
            <div className="flex items-center gap-3 welcome-fade-in">
              <LogoIcon size={48} />
              <span
                className="font-heading font-bold text-text-primary"
                style={{ fontSize: "clamp(1.75rem, 4vw, 2.5rem)" }}
              >
                {WORDMARK.split("").map((char, i) => (
                  <span
                    key={i}
                    className="welcome-char"
                    style={{ animationDelay: `${i * 60}ms` }}
                  >
                    {char}
                  </span>
                ))}
              </span>
            </div>
          )}

          {/* Step 3: Tagline */}
          {step >= 3 && (
            <p
              className="welcome-fade-in text-text-secondary font-sans tracking-wide"
              style={{ fontSize: "clamp(0.875rem, 2vw, 1.125rem)" }}
            >
              Learn{" "}
              <span className="text-text-muted">&middot;</span> Invest{" "}
              <span className="text-text-muted">&middot;</span> Trade
            </p>
          )}

          {/* Step 4: Pillar cards — HoverCard + BlurFade */}
          {step >= 4 && (
            <>
              <BlurFade delay={0} duration={0.4}>
                <p className="text-text-secondary text-sm mt-2">
                  Click any module to jump in, or set up your full workspace below.
                </p>
              </BlurFade>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 w-full mt-2">
                {PILLARS.map((pillar, i) => {
                  const Icon = pillar.icon;
                  const ROUTE_LABELS: Record<string, string> = {
                    "/learn":    "Learn",
                    "/invest":   "Invest",
                    "/trade":    "Trade",
                    "/lab":      "Lab",
                    "/automate": "Automate",
                    "/ai":       "AI",
                  };
                  const routeLabel = ROUTE_LABELS[pillar.route] ?? "Trade";
                  return (
                    <BlurFade key={pillar.title} delay={i * 0.1} duration={0.4}>
                      <HoverCard className="transition-all duration-200 cursor-pointer hover:border-accent/40">
                        <button
                          type="button"
                          onClick={() => handlePillarClick(pillar)}
                          className="w-full p-6 text-center"
                        >
                          <div className="flex justify-center mb-3">
                            <Icon className={`size-8 ${pillar.color}`} />
                          </div>
                          <h3 className="font-heading font-semibold text-text-primary text-base mb-1">
                            {pillar.title}
                          </h3>
                          <p className="text-text-muted text-sm leading-relaxed">
                            {pillar.desc}
                          </p>
                          <span className="text-xxs text-text-disabled mt-1 block">
                            &rarr; {routeLabel}
                          </span>
                        </button>
                      </HoverCard>
                    </BlurFade>
                  );
                })}
              </div>
            </>
          )}

          {/* Step 5: CTA buttons — ShimmerButton */}
          {step >= 5 && (
            <BlurFade delay={0} duration={0.5}>
              <div className="flex flex-col sm:flex-row items-center gap-4 mt-6">
                <ShimmerButton
                  onClick={() => navigate("/setup")}
                  shimmerColor="#22c55e"
                  className="px-8 py-3 text-lg font-semibold bg-profit/10 border-profit/40 text-profit hover:shadow-[0_0_30px_rgba(34,197,94,0.4)]"
                >
                  Set Up Workspace
                </ShimmerButton>
                <button
                  type="button"
                  onClick={() => navigate("/explore")}
                  className="border border-border-default text-text-primary px-8 py-3 rounded-lg text-lg hover:bg-surface-hover transition-colors duration-200 cursor-pointer"
                >
                  Explore First
                </button>
              </div>
            </BlurFade>
          )}
        </div>
      </div>
    </>
  );
}
