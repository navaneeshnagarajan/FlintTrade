/**
 * WelcomeRoute — cinematic space-themed welcome screen and auth orchestrator.
 *
 * Background: Deep space with green particle stars + continuous meteor shower.
 * Animation sequence:
 *   step 0 (0-1s):     Deep space void — particles + meteors already falling
 *   step 1 (1-2.2s):   One meteor breaks from the shower, strikes center → impact flash + shockwave ring
 *   step 2 (2.2-3.2s): Logo "F" materializes from the impact with green spark glow
 *   step 3 (3.2-4.2s): "FlintTrade" wordmark types out
 *   step 4 (4.2-5s):   Slogan words appear with color
 *   step 5 (5-6s):     CTA buttons rise up
 *
 * Meteors + particles stay visible throughout — continuous space atmosphere.
 *
 * Auth flow:
 *   setup-required  → cinematic → "Get Started" → SetupAccountRoute
 *   logged-out      → brief cinematic (auto-redirect 1.5s) → LoginRoute → /trade
 *   pin-required    → LoginRoute (PIN mode) → /trade
 *   logged-in       → redirect to last route immediately
 *   unknown         → show cinematic while checking auth status
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Moon, Sun, Monitor } from "lucide-react";

import { LogoIcon } from "@/components/brand/Logo";
import { useThemeStore } from "@/stores/themeStore";
import type { ColorMode } from "@/lib/cinematicThemes";
import { motionConfig } from "@/lib/motion";
import { useAuthStore } from "@/stores/authStore";
import LoginRoute from "@/routes/LoginRoute";
import { useModeStore } from "@/stores/modeStore";

// Magic UI
import { Particles } from "@/components/magicui/particles";
import { ShimmerButton } from "@/components/magicui/shimmer-button";

// Aceternity UI
import { Meteors } from "@/components/aceternity/meteors";

// ---------------------------------------------------------------------------
// CSS var reader — reactive to theme changes
// ---------------------------------------------------------------------------
function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  return (
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
  );
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const WORDMARK = "FlintTrade";

const SLOGAN = [
  { text: "Learn", color: "text-blue-400" },
  { text: "Invest", color: "text-emerald-400" },
  { text: "Trade", color: "text-amber-400" },
  { text: "Automate", color: "text-rose-400" },
  { text: "Analyse", color: "text-purple-400" },
  { text: "Evolve", color: "text-cyan-400" },
];

const enterEase = [0.22, 1, 0.36, 1] as const;

// ---------------------------------------------------------------------------
// Welcome-back greeting data
// ---------------------------------------------------------------------------

const TRADING_QUOTES = [
  { text: "The stock market is a device for transferring money from the impatient to the patient.", author: "Warren Buffett" },
  { text: "In investing, what is comfortable is rarely profitable.", author: "Robert Arnott" },
  { text: "The four most dangerous words in investing are: 'this time it's different.'", author: "Sir John Templeton" },
  { text: "Risk comes from not knowing what you're doing.", author: "Warren Buffett" },
  { text: "The market is never wrong — opinions often are.", author: "Jesse Livermore" },
  { text: "It's not whether you're right or wrong, it's how much money you make when you're right.", author: "George Soros" },
  { text: "Be fearful when others are greedy and greedy when others are fearful.", author: "Warren Buffett" },
  { text: "The trend is your friend until the end when it bends.", author: "Ed Seykota" },
  { text: "Markets can remain irrational longer than you can remain solvent.", author: "John Maynard Keynes" },
  { text: "Compound interest is the eighth wonder of the world.", author: "Albert Einstein" },
] as const;

function getISTGreeting(): string {
  // Compute IST hour (UTC+05:30)
  const istOffset = 5.5 * 60 * 60 * 1000;
  const nowIST = new Date(Date.now() + istOffset);
  const hour = nowIST.getUTCHours();
  if (hour >= 4 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 17) return "Good afternoon";
  return "Good evening";
}

function getRandomQuote() {
  return TRADING_QUOTES[Math.floor(Math.random() * TRADING_QUOTES.length)];
}

const GREETED_KEY = "flinttrade:greeted-today";

function shouldShowGreeting(): boolean {
  return sessionStorage.getItem(GREETED_KEY) !== new Date().toDateString();
}

function markGreeted(): void {
  sessionStorage.setItem(GREETED_KEY, new Date().toDateString());
}

// ---------------------------------------------------------------------------
// Inner flow steps (for returning users)
// ---------------------------------------------------------------------------

type FlowStep = "cinematic" | "greeting" | "login";

// ---------------------------------------------------------------------------
// Greeting screen — shown to returning users on first login of the day
// ---------------------------------------------------------------------------

function GreetingScreen({ onDone }: { onDone: () => void }) {
  const quote = useMemo(() => getRandomQuote(), []);
  const greeting = useMemo(() => getISTGreeting(), []);

  useEffect(() => {
    const t = setTimeout(onDone, 3000);
    return () => clearTimeout(t);
  }, [onDone]);

  return (
    <div
      className="min-h-screen bg-surface-base flex flex-col items-center justify-center px-6 relative cursor-pointer"
      onClick={onDone}
      role="button"
      tabIndex={0}
      aria-label="Click to continue"
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onDone(); } }}
    >
      <motion.div
        className="flex flex-col items-center gap-6 text-center max-w-md"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
      >
        <LogoIcon size={52} />
        <div className="space-y-1">
          <p className="font-heading font-bold text-2xl text-text-primary">{greeting}</p>
          <p className="text-sm text-text-muted">Welcome back to FlintTrade</p>
        </div>
        <blockquote className="rounded-xl border border-border-default bg-surface-card p-5 space-y-2">
          <p className="text-sm text-text-secondary leading-relaxed italic">&ldquo;{quote.text}&rdquo;</p>
          <footer className="text-xs text-text-muted">— {quote.author}</footer>
        </blockquote>
        <p className="text-xs text-text-muted">Redirecting to login…</p>
      </motion.div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function WelcomeRoute() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const theme = useThemeStore((s) => s.activeThemeId);
  const colorMode = useThemeStore((s) => s.mode);
  const setColorMode = useThemeStore((s) => s.setMode);
  const reducedMotion = motionConfig.prefersReducedMotion();
  const authStatus = useAuthStore((s) => s.status);

  // Which sub-screen of the returning-user flow we are showing
  const [flowStep, setFlowStep] = useState<FlowStep>("cinematic");

  // Read particle colors from CSS vars so they react to theme changes.
  // Re-computed when activeThemeId changes (theme token updates happen synchronously).
  const particleColors = useMemo(() => {
    return {
      primary:   cssVar("--particle-primary",   "#22c55e"),
      secondary: cssVar("--particle-secondary",  "#86efac"),
      tertiary:  cssVar("--particle-tertiary",   "#a3e635"),
      warm:      cssVar("--glow-color",          "#fef08a").replace(/rgba?\(.*?\)/, "#fef08a"),
      white:     "#ffffff",
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);

  const skipToEnd = useCallback(() => setStep(5), []);

  // Skip animation entirely when prefers-reduced-motion is set
  useEffect(() => {
    if (reducedMotion) setStep(5);
  }, [reducedMotion]);

  // Check auth status on mount — WelcomeRoute is not a protected route so
  // useAuthGuard does not run here. We need to query the backend ourselves
  // to know whether to show "Get Started" (setup-required) or the login form.
  useEffect(() => {
    if (authStatus !== "unknown") return;
    fetch("/ft-api/v1/auth/status")
      .then((r) => r.ok ? r.json() : Promise.reject(r))
      .then((data) => {
        if (!data.data?.is_setup) {
          useAuthStore.getState().setSetupRequired();
        } else {
          useAuthStore.getState().setLoggedOut();
        }
      })
      .catch(() => {
        // Backend unreachable — assume setup required for first-time users
        if (import.meta.env.DEV) {
          useAuthStore.getState().setSetupRequired();
        }
      });
  }, [authStatus]);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      // Only intercept Space/Enter when no interactive element (button, a, input) is focused.
      // This prevents the handler from swallowing native button activation events.
      const active = document.activeElement;
      const isInteractive =
        active instanceof HTMLButtonElement ||
        active instanceof HTMLAnchorElement ||
        active instanceof HTMLInputElement ||
        active instanceof HTMLSelectElement ||
        active instanceof HTMLTextAreaElement;
      if (isInteractive && (e.key === "Enter" || e.key === " ")) return;
      if (e.key === "Enter" || e.key === " " || e.key === "Escape") {
        e.preventDefault();
        skipToEnd();
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [skipToEnd]);

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    const s = (step: number, ms: number) => {
      timers.push(setTimeout(() => setStep((c) => (c < step ? step : c)), ms));
    };
    s(1, 1000);
    s(2, 2200);
    s(3, 3200);
    s(4, 4200);
    s(5, 5000);
    return () => timers.forEach(clearTimeout);
  }, []);

  // ------------------------------------------------------------------
  // Auth-aware routing
  // ------------------------------------------------------------------

  // If already logged in: skip straight to last route
  useEffect(() => {
    if (authStatus === "logged-in") {
      navigate("/trade", { replace: true });
    }
  }, [authStatus, navigate]);

  // Returning user (logged-out / pin-required): auto-redirect to login
  // after a brief cinematic (1.5 s). When reduced-motion: immediate.
  // For logged-out users on their first login of the day, show a greeting screen first.
  useEffect(() => {
    if (authStatus !== "logged-out" && authStatus !== "pin-required") return;
    if (flowStep !== "cinematic") return;

    const delay = reducedMotion ? 0 : 1500;
    const t = setTimeout(() => {
      setStep(5); // jump cinematic to end
      // logged-out + first login of the day → show greeting before login form
      if (authStatus === "logged-out" && shouldShowGreeting()) {
        markGreeted();
        setFlowStep("greeting");
      } else {
        setFlowStep("login");
      }
    }, delay);
    return () => clearTimeout(t);
  }, [authStatus, flowStep, reducedMotion]);

  // ------------------------------------------------------------------
  // Returning-user sub-screen handlers
  // ------------------------------------------------------------------

  function handleLoginSuccess() {
    // On daily login, default to practice mode (safety-first).
    // Mode persists in localStorage, so returning users keep their last mode
    // unless session expired (8AM IST), in which case we reset to practice.
    navigate("/trade", { replace: true });
  }

  // ------------------------------------------------------------------
  // Sub-screen renders for returning users
  // ------------------------------------------------------------------

  if (authStatus === "logged-out" && flowStep === "greeting") {
    return (
      <GreetingScreen onDone={() => setFlowStep("login")} />
    );
  }

  if (authStatus === "logged-out" && flowStep === "login") {
    return <LoginRoute onSuccess={handleLoginSuccess} mode="full" />;
  }
  if (authStatus === "pin-required" && flowStep === "login") {
    return <LoginRoute onSuccess={handleLoginSuccess} mode="pin" />;
  }

  return (
    <main aria-label="Welcome">
      <style>{`
        /* Container rotated -45deg so fireball travels along that axis.
           translateX moves it along the diagonal — positive = toward top-right */
        @keyframes fireballStrike {
          0% {
            transform: rotate(-45deg) translateX(550px);
            opacity: 0;
          }
          10% { opacity: 1; }
          90% { opacity: 1; }
          100% {
            transform: rotate(-45deg) translateX(0);
            opacity: 0;
          }
        }
        /* Flame tail flickers behind the fireball */
        @keyframes flameTail {
          0%, 100% { opacity: 0.8; transform: scaleX(1); }
          25% { opacity: 1; transform: scaleX(1.15); }
          50% { opacity: 0.7; transform: scaleX(0.9); }
          75% { opacity: 0.95; transform: scaleX(1.1); }
        }
        /* Impact — bright yellowish-green blast */
        @keyframes impactBlast {
          0% { opacity: 0; transform: scale(0.3); }
          20% { opacity: 1; transform: scale(1.2); }
          50% { opacity: 0.8; transform: scale(1.8); }
          100% { opacity: 0; transform: scale(3); }
        }
        /* Shockwave rings expand outward */
        @keyframes shockwave {
          0% { opacity: 0.8; transform: scale(0.2); }
          100% { opacity: 0; transform: scale(6); }
        }
        @keyframes shockwave2 {
          0% { opacity: 0.5; transform: scale(0.4); }
          100% { opacity: 0; transform: scale(5); }
        }
        /* Debris particles scatter from impact */
        @keyframes debris {
          0% { opacity: 1; transform: translate(0, 0) scale(1); }
          100% { opacity: 0; transform: translate(var(--dx), var(--dy)) scale(0); }
        }
        /* Logo emerges with green glow */
        @keyframes sparkReveal {
          0% { filter: drop-shadow(0 0 0 rgba(34,197,94,0)) brightness(2); }
          30% { filter: drop-shadow(0 0 30px rgba(34,197,94,0.8)) brightness(1.5); }
          100% { filter: drop-shadow(0 0 10px rgba(34,197,94,0.25)) brightness(1); }
        }
        @keyframes typeChar {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }

        /* Fireball — round glowing rock with flame tail attached via ::after */
        .hero-fireball {
          position: absolute;
          width: 14px;
          height: 14px;
          border-radius: 50%;
          background: radial-gradient(circle at 40% 40%, #fef08a 0%, #a3e635 30%, #22c55e 60%, #166534 100%);
          animation: fireballStrike 1.1s cubic-bezier(0.22, 1, 0.36, 1) forwards;
          box-shadow:
            0 0 8px 4px rgba(163,230,53,0.6),
            0 0 20px 8px rgba(34,197,94,0.4),
            0 0 40px 15px rgba(34,197,94,0.15);
        }
        /* Flame tail — extends straight right from fireball.
           Since the whole fireball is already rotated -45deg, "right" = toward top-right visually.
           No extra rotation needed — the parent's rotate handles the diagonal. */
        .hero-fireball::after {
          content: '';
          position: absolute;
          top: 50%;
          left: 100%;
          transform: translateY(-50%);
          width: 120px;
          height: 6px;
          border-radius: 0 3px 3px 0;
          background: linear-gradient(90deg, rgba(254,240,138,0.7) 0%, rgba(163,230,53,0.5) 15%, rgba(34,197,94,0.3) 40%, rgba(34,197,94,0.08) 65%, transparent 100%);
          animation: flameTail 0.12s ease-in-out infinite;
          box-shadow: 0 0 10px 3px rgba(34,197,94,0.15);
        }

        /* Impact blast — yellowish-green explosion */
        .impact-blast {
          position: absolute;
          width: 100px;
          height: 100px;
          border-radius: 50%;
          background: radial-gradient(circle,
            rgba(254,240,138,0.9) 0%,
            rgba(163,230,53,0.7) 25%,
            rgba(34,197,94,0.4) 50%,
            transparent 70%
          );
          animation: impactBlast 0.6s ease-out 1s forwards;
          opacity: 0;
        }
        /* Shockwave rings */
        .shock-ring {
          position: absolute;
          width: 24px;
          height: 24px;
          border-radius: 50%;
          border: 2px solid rgba(163,230,53,0.6);
          animation: shockwave 0.8s ease-out 1.05s forwards;
          opacity: 0;
        }
        .shock-ring-2 {
          position: absolute;
          width: 24px;
          height: 24px;
          border-radius: 50%;
          border: 1.5px solid rgba(34,197,94,0.4);
          animation: shockwave2 1s ease-out 1.15s forwards;
          opacity: 0;
        }
        /* Debris particles — scattered on impact */
        .debris-particle {
          position: absolute;
          width: 3px;
          height: 3px;
          border-radius: 50%;
          background: #a3e635;
          animation: debris 0.7s ease-out 1s forwards;
          opacity: 0;
          box-shadow: 0 0 4px 1px rgba(163,230,53,0.5);
        }
        /* Logo glow reveal */
        .logo-reveal {
          animation: sparkReveal 2s ease-in-out 0.2s;
        }
        .welcome-char {
          display: inline-block;
          opacity: 0;
          animation: typeChar 0.08s ease-out forwards;
        }
      `}</style>

      <h1 className="sr-only">Welcome to FlintTrade</h1>

      {/* Dark / light / system mode toggle — top-right, always visible */}
      <div className="absolute top-6 right-6 flex gap-1 z-50">
        {(["dark", "light", "system"] as const).map((m) => {
          const Icon = m === "dark" ? Moon : m === "light" ? Sun : Monitor;
          const isActive = colorMode === m;
          return (
            <button
              key={m}
              onClick={() => setColorMode(m as ColorMode)}
              aria-label={`Switch to ${m} mode`}
              className={`p-1.5 rounded transition-colors focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
                isActive
                  ? "bg-accent/20 text-accent"
                  : "text-text-muted hover:text-text-primary"
              }`}
            >
              <Icon size={14} />
            </button>
          );
        })}
      </div>

      <div className="min-h-screen bg-surface-base flex flex-col items-center justify-center relative overflow-hidden select-none">

        {/* ====== SPACE BACKGROUND — always visible ====== */}

        {/* Deep space — multi-layer particles as distant stars and planets */}
        <Particles quantity={50} color={particleColors.primary}   size={0.4} className="opacity-10" />
        <Particles quantity={15} color={particleColors.secondary} size={1.5} className="opacity-20" />
        <Particles quantity={6}  color={particleColors.tertiary}  size={2.5} className="opacity-15" />
        <Particles quantity={4}  color={particleColors.warm}      size={3.0} className="opacity-10" />
        <Particles quantity={3}  color={particleColors.white}     size={2.0} className="opacity-5" />

        {/* Continuous meteor shower — always falling */}
        <Meteors number={15} />

        {/* Subtle radial glow at center — nebula feel */}
        <div
          className="absolute pointer-events-none"
          style={{
            width: 600,
            height: 600,
            borderRadius: "50%",
            background: "radial-gradient(circle, rgba(34,197,94,0.04) 0%, transparent 70%)",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
          }}
        />

        {/* ====== CINEMATIC CONTENT — fixed layout, elements fade into place ====== */}
        <div className="relative z-10 flex flex-col items-center px-4" style={{ gap: 24 }}>

          {/* Logo area — meteor strike + logo emerge */}
          <div className="relative flex items-center justify-center" style={{ width: 140, height: 120 }}>

            {/* Step 1: Fireball with flame tail — strikes center → blast + debris */}
            {step >= 1 && step < 3 && (
              <>
                {/* Fireball (flame tail is ::after pseudo-element, moves together) */}
                <div className="hero-fireball" />

                {/* Impact blast */}
                <div className="impact-blast" />

                {/* Shockwave rings */}
                <div className="shock-ring" />
                <div className="shock-ring-2" />

                {/* Debris particles scattering from impact */}
                <div className="debris-particle" style={{ "--dx": "-60px", "--dy": "-40px" } as React.CSSProperties} />
                <div className="debris-particle" style={{ "--dx": "50px", "--dy": "-55px", animationDelay: "1.05s" } as React.CSSProperties} />
                <div className="debris-particle" style={{ "--dx": "-45px", "--dy": "35px", animationDelay: "1.08s" } as React.CSSProperties} />
                <div className="debris-particle" style={{ "--dx": "65px", "--dy": "30px", animationDelay: "1.03s" } as React.CSSProperties} />
                <div className="debris-particle" style={{ "--dx": "-30px", "--dy": "-65px", animationDelay: "1.1s" } as React.CSSProperties} />
                <div className="debris-particle" style={{ "--dx": "40px", "--dy": "55px", animationDelay: "1.06s" } as React.CSSProperties} />
                <div className="debris-particle" style={{ "--dx": "-70px", "--dy": "10px", animationDelay: "1.12s" } as React.CSSProperties} />
                <div className="debris-particle" style={{ "--dx": "25px", "--dy": "-70px", animationDelay: "1.02s" } as React.CSSProperties} />
              </>
            )}

            {/* Step 2: Logo emerges from impact point */}
            <AnimatePresence>
              {step >= 2 && (
                <motion.div
                  className="logo-reveal absolute"
                  initial={{ scale: 0.88, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ duration: 0.7, ease: enterEase }}
                >
                  <LogoIcon size={88} />
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Wordmark — always in DOM, visibility controlled by opacity */}
          <div style={{ height: 56 }}>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: step >= 3 ? 1 : 0 }}
              transition={{ duration: 0.5, ease: "easeOut" }}
            >
              <span
                className="font-heading font-bold text-text-primary"
                style={{ fontSize: "clamp(2rem, 5vw, 3.5rem)" }}
              >
                {step >= 3 && WORDMARK.split("").map((char, i) => (
                  <span
                    key={i}
                    className="welcome-char"
                    style={{ animationDelay: `${i * 65}ms` }}
                  >
                    {char}
                  </span>
                ))}
              </span>
            </motion.div>
          </div>

          {/* Slogan — always in DOM, fades in */}
          <div style={{ height: 28 }}>
            <motion.div
              className="flex flex-wrap items-center justify-center gap-x-1.5 gap-y-1"
              initial={{ opacity: 0 }}
              animate={{ opacity: step >= 4 ? 1 : 0 }}
              transition={{ duration: 0.5, ease: "easeOut" }}
            >
              {step >= 4 && SLOGAN.map((word, i) => (
                <motion.span
                  key={word.text}
                  className={`${word.color} font-sans font-medium tracking-wide`}
                  style={{ fontSize: "clamp(0.875rem, 2vw, 1.2rem)" }}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{
                    delay: i * 0.06,
                    duration: 0.4,
                    ease: "easeOut",
                  }}
                >
                  {word.text}
                  {i < SLOGAN.length - 1 && (
                    <span className="text-text-muted ml-1.5">·</span>
                  )}
                </motion.span>
              ))}
            </motion.div>
          </div>

          {/* Tagline + feature bullets — fade in with CTA step */}
          <motion.div
            className="flex flex-col items-center gap-3 text-center"
            initial={{ opacity: 0 }}
            animate={{ opacity: step >= 5 ? 1 : 0 }}
            transition={{ duration: 0.8, ease: "easeOut" }}
            aria-label="FlintTrade feature overview"
          >
            <p className="text-sm text-text-secondary font-sans">
              Open-source trading platform for Indian markets
            </p>
            <ul className="space-y-1.5 text-left" role="list">
              {[
                "Trade stocks, F&O, commodities with 30+ brokers via OpenAlgo",
                "AI-powered strategy suggestions and 101 backtest strategies",
                "Real-time option chain, Greeks, IV surface, and order flow analysis",
                "SIP tracking, tax reports, and portfolio overlap detection",
              ].map((bullet) => (
                <li
                  key={bullet}
                  className="flex items-start gap-2 text-xs text-text-muted font-sans"
                >
                  <span className="text-accent mt-0.5 shrink-0" aria-hidden="true">•</span>
                  <span>{bullet}</span>
                </li>
              ))}
            </ul>
          </motion.div>

          {/* CTA buttons — only shown for first-time / setup-required users */}
          <div className="mt-4 flex flex-col items-center gap-3">
            <motion.div
              className="flex flex-col sm:flex-row items-center gap-4"
              initial={{ opacity: 0 }}
              animate={{ opacity: step >= 5 && authStatus === "setup-required" ? 1 : 0 }}
              transition={{ duration: 1, ease: "easeOut" }}
            >
              <ShimmerButton
                onClick={() => navigate("/setup-account")}
                shimmerColor="#22c55e"
                className="px-10 py-3.5 text-lg font-semibold bg-profit/10 border-profit/40 text-profit hover:shadow-[0_0_30px_rgba(34,197,94,0.4)]"
              >
                Get Started
              </ShimmerButton>
            </motion.div>

            {/* Explore Demo — bypasses account setup entirely */}
            <motion.button
              initial={{ opacity: 0 }}
              animate={{ opacity: step >= 5 && authStatus === "setup-required" ? 1 : 0 }}
              transition={{ duration: 1, delay: 0.15, ease: "easeOut" }}
              onClick={() => {
                useModeStore.getState().setMode("explore");
                useAuthStore.getState().setLoggedIn("demo-user", "Explorer", "");
                navigate("/trade");
              }}
              className="text-sm text-text-muted hover:text-text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded px-2 py-1"
              aria-label="Explore FlintTrade in demo mode without creating an account"
            >
              Explore FlintTrade →
            </motion.button>

            {/* For returning users the cinematic plays while auto-redirecting — no buttons */}
            {(authStatus === "logged-out" || authStatus === "pin-required") && (
              <motion.p
                className="text-xs text-text-muted text-center"
                initial={{ opacity: 0 }}
                animate={{ opacity: step >= 3 ? 0.6 : 0 }}
                transition={{ duration: 0.6 }}
              >
                Redirecting to login…
              </motion.p>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
