/**
 * WelcomeRoute - cinematic space-themed welcome screen and auth orchestrator.
 *
 * This route is the visual source of truth for the public entry flow: centred
 * logo, particles, meteors, shimmer CTA, and a calm glassy control layer.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { useNavigate } from "react-router";
import { AnimatePresence, motion } from "framer-motion";
import { Monitor, Moon, Sun } from "lucide-react";

import { BRAND_REVEAL_TIMELINE, BRAND_SLOGAN_WORDS, BRAND_WORDMARK } from "@flinttrade/design-system/brand";

import { Meteors } from "@/components/aceternity/meteors";
import { LogoIcon } from "@/components/brand/Logo";
import { Particles } from "@/components/magicui/particles";
import { ShimmerButton } from "@/components/magicui/shimmer-button";
import { Button } from "@/components/ui/button";
import type { ColorMode } from "@/lib/cinematicThemes";
import { motionConfig } from "@/lib/motion";
import { cn } from "@/lib/utils";
import LoginRoute from "@/routes/LoginRoute";
import { buildHeaders, getBase } from "@/services/ftApi.helpers";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { markDemoSessionActive } from "@/lib/demoSession";
import { useThemeStore } from "@/stores/themeStore";

const WORDMARK = BRAND_WORDMARK;

// Words come from the design-system brand copy (the single source of truth
// shared with the public site hero). The Tailwind colour classes pair
// one-to-one with BRAND_SLOGAN_COLOURS (blue/emerald/amber/rose/purple/cyan)
// and must stay literal here so Tailwind's scanner generates them.
export const SLOGAN = [
  { text: BRAND_SLOGAN_WORDS[0], color: "text-blue-400" },
  { text: BRAND_SLOGAN_WORDS[1], color: "text-emerald-400" },
  { text: BRAND_SLOGAN_WORDS[2], color: "text-amber-400" },
  { text: BRAND_SLOGAN_WORDS[3], color: "text-rose-400" },
  { text: BRAND_SLOGAN_WORDS[4], color: "text-purple-400" },
  { text: BRAND_SLOGAN_WORDS[5], color: "text-cyan-400" },
] as const;

// Cinematic step schedule derived from the shared brand reveal timeline so
// the terminal welcome reveal and the site hero stay frame-matched. Exported
// for the parity test.
export const CINEMATIC_STEP_SCHEDULE = [
  [1, BRAND_REVEAL_TIMELINE.sequenceStartMs],
  [2, BRAND_REVEAL_TIMELINE.logoMs],
  [3, BRAND_REVEAL_TIMELINE.wordmarkMs],
  [4, BRAND_REVEAL_TIMELINE.sloganMs],
  [5, BRAND_REVEAL_TIMELINE.contentMs],
] as const;

const WELCOME_FEATURES = [
  "OpenAlgo bridge plus verified native brokers",
  "Explore, Practice, and Live safety modes",
  "Option chain, Greeks, order flow, and depth",
  "Strategy lab, SIP tracking, and AI context",
] as const;

const TRADING_QUOTES = [
  { text: "The stock market is a device for transferring money from the impatient to the patient.", author: "Warren Buffett" },
  { text: "In investing, what is comfortable is rarely profitable.", author: "Robert Arnott" },
  { text: "Risk comes from not knowing what you are doing.", author: "Warren Buffett" },
  { text: "The market is never wrong; opinions often are.", author: "Jesse Livermore" },
  { text: "Be fearful when others are greedy and greedy when others are fearful.", author: "Warren Buffett" },
] as const;

const GREETED_KEY = "flinttrade:greeted-today";
const enterEase = [0.22, 1, 0.36, 1] as const;
const silkyEase = [0.16, 1, 0.3, 1] as const;
const smoothSpring = {
  type: "spring",
  stiffness: 120,
  damping: 28,
  mass: 0.9,
} as const;

type FlowStep = "cinematic" | "greeting" | "login";

const DEBRIS_PARTICLES = [
  { dx: "-60px", dy: "-40px", delay: "1s" },
  { dx: "50px", dy: "-55px", delay: "1.05s" },
  { dx: "-45px", dy: "35px", delay: "1.08s" },
  { dx: "65px", dy: "30px", delay: "1.03s" },
  { dx: "-30px", dy: "-65px", delay: "1.1s" },
  { dx: "40px", dy: "55px", delay: "1.06s" },
  { dx: "-70px", dy: "10px", delay: "1.12s" },
  { dx: "25px", dy: "-70px", delay: "1.02s" },
] as const;

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function getISTGreeting(): string {
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

function shouldShowGreeting(): boolean {
  return sessionStorage.getItem(GREETED_KEY) !== new Date().toDateString();
}

function markGreeted(): void {
  sessionStorage.setItem(GREETED_KEY, new Date().toDateString());
}

function ThemeToggle() {
  const colorMode = useThemeStore((s) => s.mode);
  const setColorMode = useThemeStore((s) => s.setMode);

  return (
    <div className="absolute right-5 top-5 z-50 inline-flex rounded-full border border-border-default/70 bg-surface-card/70 p-0.5 shadow-xl shadow-black/20 backdrop-blur-xl">
      {(["dark", "light", "system"] as const).map((mode) => {
        const Icon = mode === "dark" ? Moon : mode === "light" ? Sun : Monitor;
        const isActive = colorMode === mode;

        return (
          <button
            key={mode}
            type="button"
            onClick={() => setColorMode(mode as ColorMode)}
            aria-label={`Switch to ${mode} mode`}
            className={cn(
              "grid size-8 place-items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
              isActive
                ? "bg-accent/20 text-accent shadow-[0_0_18px_rgba(34,197,94,0.22)]"
                : "text-text-muted hover:text-text-primary",
            )}
          >
            <Icon size={14} aria-hidden="true" />
          </button>
        );
      })}
    </div>
  );
}

function CinematicBackdrop({ particleColors }: { particleColors: string[] }) {
  return (
    <div className="absolute inset-0 overflow-hidden" aria-hidden="true">
      <Particles
        quantity={110}
        colors={particleColors}
        sizeRange={[0.8, 2.2]}
        behavior="drift"
        seed={19_841}
        className="opacity-45"
      />
      <Particles
        quantity={36}
        color="#ffffff"
        sizeRange={[1.1, 2.8]}
        behavior="pulse"
        seed={7_721}
        className="opacity-25"
      />
      <Particles
        quantity={42}
        colors={["#22c55e", "#38bdf8", "#a3e635"]}
        sizeRange={[0.4, 1.3]}
        behavior="float"
        seed={3_109}
        className="opacity-30"
      />
      <Meteors number={18} seed={8_021} />
      <div className="absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-surface-base via-surface-base/55 to-transparent" />
    </div>
  );
}

function GreetingScreen({ onDone }: { onDone: () => void }) {
  const quote = useMemo(() => getRandomQuote(), []);
  const greeting = useMemo(() => getISTGreeting(), []);
  const particleColors = useMemo(() => ["#22c55e", "#38bdf8", "#a3e635"], []);

  useEffect(() => {
    const timer = setTimeout(onDone, 3000);
    return () => clearTimeout(timer);
  }, [onDone]);

  return (
    <main
      aria-label="Welcome back"
      className="relative flex min-h-screen cursor-pointer flex-col items-center justify-center overflow-hidden bg-surface-base px-6 text-center"
      onClick={onDone}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onDone();
        }
      }}
    >
      <CinematicBackdrop particleColors={particleColors} />
      <motion.div
        className="relative z-10 flex max-w-md flex-col items-center gap-6"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: enterEase }}
      >
        <LogoIcon size={56} />
        <div className="space-y-1">
          <h1 className="font-heading text-3xl font-bold text-text-primary">{greeting}</h1>
          <p className="text-sm text-text-muted">Welcome back to FlintTrade</p>
        </div>
        <blockquote className="space-y-2 rounded-xl border border-border-default/80 bg-surface-card/70 p-5 shadow-2xl shadow-black/20 backdrop-blur-xl">
          <p className="text-sm italic leading-relaxed text-text-secondary">&quot;{quote.text}&quot;</p>
          <footer className="text-xs text-text-muted">- {quote.author}</footer>
        </blockquote>
        <p className="text-xs text-text-muted">Redirecting to login...</p>
      </motion.div>
    </main>
  );
}

function LogoImpactReveal({ step }: { step: number }) {
  return (
    <div className="relative flex h-36 w-44 items-center justify-center">
      {step >= 1 && step < 3 && (
        <>
          <div className="hero-fireball" />
          <div className="impact-blast" />
          <div className="shock-ring" />
          <div className="shock-ring-2" />
          {DEBRIS_PARTICLES.map((particle) => (
            <div
              key={`${particle.dx}-${particle.dy}`}
              className="debris-particle"
              style={{
                "--dx": particle.dx,
                "--dy": particle.dy,
                animationDelay: particle.delay,
              } as CSSProperties}
            />
          ))}
        </>
      )}

      <AnimatePresence>
        {step >= 2 && (
          <motion.div
            className="logo-reveal absolute grid size-32 place-items-center will-change-transform"
            initial={{ opacity: 0, scale: 0.74, y: 12, filter: "blur(10px)" }}
            animate={{ opacity: 1, scale: 1, y: 0, filter: "blur(0px)" }}
            transition={smoothSpring}
          >
            <LogoIcon size={84} aria-hidden="true" />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function WelcomeRoute() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [flowStep, setFlowStep] = useState<FlowStep>("cinematic");
  const theme = useThemeStore((s) => s.activeThemeId);
  const reducedMotion = motionConfig.prefersReducedMotion();
  const authStatus = useAuthStore((s) => s.status);

  const particleColors = useMemo(
    () => [
      cssVar("--particle-primary", "#22c55e"),
      cssVar("--particle-secondary", "#86efac"),
      cssVar("--particle-tertiary", "#38bdf8"),
    ],
    // `cssVar` reads the live computed style, so the active theme is a real
    // dependency that no static analysis can see (same shape as
    // PublicRouteShell).
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see above
    [theme],
  );

  const skipToEnd = useCallback(() => setStep(5), []);

  useEffect(() => {
    if (reducedMotion) setStep(5);
  }, [reducedMotion]);

  useEffect(() => {
    if (authStatus !== "unknown") return;

    // Time-box the probe so a hung backend can't strand the user on
    // "Checking workspace…" forever.
    const controller = new AbortController();
    let cancelled = false;
    const timeout = setTimeout(() => controller.abort(), 6000);

    fetch(`${getBase()}/v1/auth/status`, { headers: buildHeaders(false), signal: controller.signal })
      .then((response) => (response.ok ? response.json() : Promise.reject(response)))
      .then((data) => {
        if (!data.data?.is_setup) {
          useAuthStore.getState().setSetupRequired();
        } else {
          useAuthStore.getState().setLoggedOut();
        }
      })
      .catch(() => {
        // React Strict Mode intentionally mounts, cleans up, and remounts
        // effects in development. That cleanup abort is not a failed backend
        // probe and must not overwrite a valid returning-user state.
        if (cancelled) return;
        // Backend unreachable, errored, or timed out. Degrade gracefully in
        // every build (not just DEV) so the welcome screen always offers a way
        // forward — "Get Started" once the backend is up, and "Explore
        // FlintTrade" which needs no backend at all. Without this the
        // production welcome screen hangs on "Checking workspace…" with no exit.
        if (useAuthStore.getState().status === "unknown") {
          useAuthStore.getState().setSetupRequired();
        }
      })
      .finally(() => clearTimeout(timeout));

    return () => {
      cancelled = true;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [authStatus]);

  useEffect(() => {
    function handleKey(event: KeyboardEvent) {
      const active = document.activeElement;
      const isInteractive =
        active instanceof HTMLButtonElement ||
        active instanceof HTMLAnchorElement ||
        active instanceof HTMLInputElement ||
        active instanceof HTMLSelectElement ||
        active instanceof HTMLTextAreaElement;

      if (isInteractive && (event.key === "Enter" || event.key === " ")) return;
      if (event.key === "Enter" || event.key === " " || event.key === "Escape") {
        event.preventDefault();
        skipToEnd();
      }
    }

    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [skipToEnd]);

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    const schedule = (nextStep: number, ms: number) => {
      timers.push(setTimeout(() => setStep((current) => (current < nextStep ? nextStep : current)), ms));
    };

    for (const [nextStep, ms] of CINEMATIC_STEP_SCHEDULE) {
      schedule(nextStep, ms);
    }

    return () => timers.forEach(clearTimeout);
  }, []);

  useEffect(() => {
    if (authStatus === "logged-in") {
      navigate("/trade", { replace: true });
    }
  }, [authStatus, navigate]);

  useEffect(() => {
    if (authStatus !== "logged-out") return;

    try {
      const raw = localStorage.getItem("flinttrade:setup-progress");
      if (!raw) return;
      const saved = JSON.parse(raw) as { accountCreated?: boolean; currentStep?: number };
      if (saved?.accountCreated && typeof saved.currentStep === "number" && saved.currentStep < 6) {
        navigate("/setup-account", { replace: true });
      }
    } catch {
      // Ignore corrupt progress and continue to sign-in.
    }
  }, [authStatus, navigate]);

  useEffect(() => {
    if (authStatus !== "logged-out" && authStatus !== "pin-required") return;
    if (flowStep !== "cinematic") return;

    const timer = setTimeout(() => {
      setStep(5);
      if (authStatus === "logged-out" && shouldShowGreeting()) {
        markGreeted();
        setFlowStep("greeting");
      } else {
        setFlowStep("login");
      }
    }, reducedMotion ? 0 : 1500);

    return () => clearTimeout(timer);
  }, [authStatus, flowStep, reducedMotion]);

  function handleLoginSuccess() {
    navigate("/trade", { replace: true });
  }

  function handleExplore() {
    // Installed app "Try with sample data" enters normal Home/persona workspace directly in Explore mode.
    // /explore route is retained only for public demo build/URL compatibility (build-aware route contract in main.tsx).
    // British English: "Try with sample data".
    useModeStore.getState().setMode("explore");
    markDemoSessionActive();
    useAuthStore.getState().setLoggedIn("demo-user", "Explorer", "");
    navigate("/home");
  }

  if (authStatus === "logged-out" && flowStep === "greeting") {
    return <GreetingScreen onDone={() => setFlowStep("login")} />;
  }

  if (authStatus === "logged-out" && flowStep === "login") {
    return <LoginRoute onSuccess={handleLoginSuccess} mode="full" />;
  }

  if (authStatus === "pin-required" && flowStep === "login") {
    return <LoginRoute onSuccess={handleLoginSuccess} mode="pin" />;
  }

  const showSetupActions = authStatus === "setup-required";

  return (
    <main aria-label="Welcome" className="relative min-h-screen overflow-hidden bg-surface-base text-text-primary">
      <style>{`
        @keyframes fireballStrike {
          0% { transform: rotate(-45deg) translateX(550px); opacity: 0; }
          10% { opacity: 1; }
          90% { opacity: 1; }
          100% { transform: rotate(-45deg) translateX(0); opacity: 0; }
        }
        @keyframes flameTail {
          0%, 100% { opacity: 0.8; transform: translateY(-50%) scaleX(1); }
          25% { opacity: 1; transform: translateY(-50%) scaleX(1.15); }
          50% { opacity: 0.7; transform: translateY(-50%) scaleX(0.9); }
          75% { opacity: 0.95; transform: translateY(-50%) scaleX(1.1); }
        }
        @keyframes impactBlast {
          0% { opacity: 0; transform: scale(0.3); }
          20% { opacity: 1; transform: scale(1.2); }
          50% { opacity: 0.8; transform: scale(1.8); }
          100% { opacity: 0; transform: scale(3); }
        }
        @keyframes shockwave {
          0% { opacity: 0.8; transform: scale(0.2); }
          100% { opacity: 0; transform: scale(6); }
        }
        @keyframes shockwave2 {
          0% { opacity: 0.5; transform: scale(0.4); }
          100% { opacity: 0; transform: scale(5); }
        }
        @keyframes debris {
          0% { opacity: 1; transform: translate(0, 0) scale(1); }
          100% { opacity: 0; transform: translate(var(--dx), var(--dy)) scale(0); }
        }
        .hero-fireball {
          position: absolute;
          width: 14px;
          height: 14px;
          border-radius: 999px;
          background: radial-gradient(circle at 40% 40%, #fef08a 0%, #a3e635 30%, #22c55e 60%, #166534 100%);
          animation: fireballStrike 1.1s cubic-bezier(0.22, 1, 0.36, 1) forwards;
          box-shadow:
            0 0 8px 4px rgba(163,230,53,0.6),
            0 0 20px 8px rgba(34,197,94,0.4),
            0 0 40px 15px rgba(34,197,94,0.15);
        }
        .hero-fireball::after {
          content: "";
          position: absolute;
          top: 50%;
          left: 100%;
          width: 120px;
          height: 6px;
          border-radius: 0 3px 3px 0;
          background: linear-gradient(90deg, rgba(254,240,138,0.7) 0%, rgba(163,230,53,0.5) 15%, rgba(34,197,94,0.3) 40%, rgba(34,197,94,0.08) 65%, transparent 100%);
          animation: flameTail 0.12s ease-in-out infinite;
          box-shadow: 0 0 10px 3px rgba(34,197,94,0.15);
        }
        .impact-blast {
          position: absolute;
          width: 100px;
          height: 100px;
          border-radius: 999px;
          background: radial-gradient(circle, rgba(254,240,138,0.9) 0%, rgba(163,230,53,0.7) 25%, rgba(34,197,94,0.4) 50%, transparent 70%);
          animation: impactBlast 0.6s ease-out 1s forwards;
          opacity: 0;
        }
        .shock-ring,
        .shock-ring-2 {
          position: absolute;
          width: 24px;
          height: 24px;
          border-radius: 999px;
          opacity: 0;
        }
        .shock-ring {
          border: 2px solid rgba(163,230,53,0.6);
          animation: shockwave 0.8s ease-out 1.05s forwards;
        }
        .shock-ring-2 {
          border: 1.5px solid rgba(34,197,94,0.4);
          animation: shockwave2 1s ease-out 1.15s forwards;
        }
        .debris-particle {
          position: absolute;
          width: 3px;
          height: 3px;
          border-radius: 999px;
          background: #a3e635;
          animation: debris 0.7s ease-out forwards;
          opacity: 0;
          box-shadow: 0 0 4px 1px rgba(163,230,53,0.5);
        }
        .welcome-char {
          display: inline-block;
          transform-origin: 50% 80%;
          will-change: transform, opacity, filter;
        }
        @media (prefers-reduced-motion: reduce) {
          .hero-fireball,
          .impact-blast,
          .shock-ring,
          .shock-ring-2,
          .debris-particle {
            animation: none;
            opacity: 1;
          }
        }
      `}</style>

      <h1 className="sr-only">Welcome to FlintTrade</h1>
      <ThemeToggle />
      <CinematicBackdrop particleColors={particleColors} />

      <div className="relative z-10 flex min-h-screen flex-col items-center justify-center px-4 py-16 text-center">
        <motion.div
          className="flex max-w-3xl flex-col items-center gap-7"
          layout
          transition={{ layout: { duration: 0.85, ease: silkyEase } }}
        >
          <LogoImpactReveal step={step} />

          <AnimatePresence>
            {step >= 3 && (
              <motion.div
                className="space-y-3"
                initial={{ opacity: 0, y: 10, filter: "blur(2px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.34, ease: silkyEase }}
              >
                <h2
                  className="font-heading text-5xl font-bold leading-none text-text-primary drop-shadow-[0_0_36px_rgba(34,197,94,0.16)] sm:text-7xl"
                  aria-label={WORDMARK}
                >
                  {WORDMARK.split("").map((char, index) => (
                    <motion.span
                      key={`${char}-${index}`}
                      aria-hidden="true"
                      className="welcome-char"
                      initial={{ opacity: 0, y: 10, scale: 0.99, filter: "blur(2px)" }}
                      animate={{ opacity: 1, y: 0, scale: 1, filter: "blur(0px)" }}
                      transition={{ duration: 0.24, ease: silkyEase, delay: 0.02 + index * 0.012 }}
                    >
                      {char}
                    </motion.span>
                  ))}
                </h2>

                {step >= 4 && (
                  <motion.div
                    className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1"
                    initial={{ opacity: 0, y: 8, filter: "blur(2px)" }}
                    animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                    transition={{ duration: 0.28, ease: silkyEase }}
                  >
                    {SLOGAN.map((word, index) => (
                      <motion.span
                        key={word.text}
                        className={cn("font-sans text-sm font-medium tracking-wide sm:text-lg", word.color)}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.24, ease: silkyEase, delay: index * 0.02 }}
                      >
                        {word.text}
                        {index < SLOGAN.length - 1 && (
                          <span className="ml-2 text-text-muted">.</span>
                        )}
                      </motion.span>
                    ))}
                  </motion.div>
                )}
              </motion.div>
            )}
          </AnimatePresence>

          <AnimatePresence>
            {step >= 5 && (
              <motion.div
                className="mx-auto max-w-2xl space-y-5"
                initial={{ opacity: 0, y: 12, scale: 0.99, filter: "blur(2px)" }}
                animate={{ opacity: 1, y: 0, scale: 1, filter: "blur(0px)" }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.34, ease: silkyEase }}
              >
                <motion.p
                  className="mx-auto max-w-xl text-sm leading-relaxed text-text-secondary sm:text-base"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.26, ease: silkyEase, delay: 0.04 }}
                >
                  Open-source self-hosted trading software for local research, simulated
                  testing, manual orders, automation, and AI-assisted workflows. One
                  native app for macOS, Windows, and Linux.
                </motion.p>
                <div className="mx-auto grid max-w-xl gap-2 text-left sm:grid-cols-2">
                  {WELCOME_FEATURES.map((item, index) => (
                    <motion.div
                      key={item}
                      className="rounded-lg border border-border-default/70 bg-surface-card/55 px-3 py-2 text-xs text-text-secondary shadow-lg shadow-black/10 backdrop-blur-xl"
                      initial={{ opacity: 0, y: 14, scale: 0.98 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      transition={{ duration: 0.28, ease: silkyEase, delay: 0.06 + index * 0.025 }}
                    >
                      <span className="mr-2 text-accent" aria-hidden="true">•</span>
                      {item}
                    </motion.div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <AnimatePresence>
            {step >= 5 && (
              <motion.div
                className="flex flex-col items-center gap-3"
                initial={{ opacity: 0, y: 10, scale: 0.99, filter: "blur(2px)" }}
                animate={{ opacity: 1, y: 0, scale: 1, filter: "blur(0px)" }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.3, ease: silkyEase, delay: 0.08 }}
              >
                {showSetupActions ? (
                  <>
                    <ShimmerButton
                      onClick={() => navigate("/setup-account")}
                      shimmerColor="#22c55e"
                      className="px-10 py-3.5 text-base font-semibold bg-profit/10 border-profit/45 text-profit hover:shadow-[0_0_34px_rgba(34,197,94,0.36)]"
                    >
                      Get Started
                    </ShimmerButton>
                    <button
                      type="button"
                      onClick={handleExplore}
                      className="rounded px-2 py-1 text-sm text-text-muted transition-colors hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                      aria-label="Try with sample data without creating an account"
                    >
                      Try with sample data →
                    </button>
                  </>
                ) : (
                  <Button type="button" variant="ghost" onClick={skipToEnd}>
                    Checking workspace...
                  </Button>
                )}

                {(authStatus === "logged-out" || authStatus === "pin-required") && (
                  <p className="text-xs text-text-muted">Redirecting to login...</p>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      </div>
    </main>
  );
}
