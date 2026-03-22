/**
 * WelcomeRoute — cinematic space-themed welcome screen.
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
 * Skip → navigates to /explore.
 */

import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Moon, Circle, Leaf, Waves, Sun } from "lucide-react";

import { LogoIcon } from "@/components/brand/Logo";
import { useSettingsStore } from "@/stores/settingsStore";

// Magic UI
import { Particles } from "@/components/magicui/particles";
import { ShimmerButton } from "@/components/magicui/shimmer-button";

// Aceternity UI
import { Meteors } from "@/components/aceternity/meteors";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const THEME_OPTIONS = [
  { id: "midnight" as const, icon: Moon, label: "Midnight" },
  { id: "obsidian" as const, icon: Circle, label: "Obsidian" },
  { id: "terminal-green" as const, icon: Leaf, label: "Green" },
  { id: "ocean-blue" as const, icon: Waves, label: "Blue" },
  { id: "light" as const, icon: Sun, label: "Light" },
];

const WORDMARK = "FlintTrade";

const SLOGAN = [
  { text: "Learn", color: "text-blue-400" },
  { text: "Invest", color: "text-emerald-400" },
  { text: "Trade", color: "text-amber-400" },
  { text: "Automate", color: "text-rose-400" },
  { text: "Analyze", color: "text-purple-400" },
  { text: "Evolve", color: "text-cyan-400" },
];

const enterEase = [0.22, 1, 0.36, 1] as const;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function WelcomeRoute() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const theme = useSettingsStore((s) => s.theme);

  const skipToEnd = useCallback(() => setStep(5), []);

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

  return (
    <>
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

      <div className="min-h-screen bg-surface-base flex flex-col items-center justify-center relative overflow-hidden select-none">

        {/* ====== SPACE BACKGROUND — always visible ====== */}

        {/* Deep space — multi-layer particles as distant stars and planets */}
        <Particles quantity={50} color="#22c55e" size={0.4} className="opacity-10" />
        <Particles quantity={15} color="#86efac" size={1.5} className="opacity-20" />
        <Particles quantity={6} color="#a3e635" size={2.5} className="opacity-15" />
        <Particles quantity={4} color="#fef08a" size={3.0} className="opacity-10" />
        <Particles quantity={3} color="#ffffff" size={2.0} className="opacity-8" />

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

        {/* ====== UI CHROME ====== */}

        {/* Theme switcher — top-left */}
        <motion.div
          className="fixed top-4 left-4 flex items-center gap-1 z-50"
          initial={{ opacity: 0 }}
          animate={{ opacity: step >= 2 ? 1 : 0 }}
          transition={{ duration: 0.6, ease: enterEase }}
        >
          {THEME_OPTIONS.map((t) => {
            const ThemeIcon = t.icon;
            return (
              <button
                key={t.id}
                onClick={() => useSettingsStore.getState().setTheme(t.id)}
                className={`p-1.5 rounded transition-colors duration-150 cursor-pointer ${
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
        </motion.div>

        {/* Skip → /explore */}
        <motion.button
          onClick={() => navigate("/explore")}
          className="absolute top-6 right-6 text-xs text-text-muted hover:text-text-primary cursor-pointer z-50"
          initial={{ opacity: 0 }}
          animate={{ opacity: step >= 1 ? 0.5 : 0 }}
          whileHover={{ opacity: 1 }}
          transition={{ duration: 0.4 }}
        >
          Skip →
        </motion.button>

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

          {/* CTA buttons — always in DOM, fade in */}
          <div style={{ height: 56 }} className="mt-4">
            <motion.div
              className="flex flex-col sm:flex-row items-center gap-4"
              initial={{ opacity: 0 }}
              animate={{ opacity: step >= 5 ? 1 : 0 }}
              transition={{ duration: 1, ease: "easeOut" }}
            >
              <ShimmerButton
                onClick={() => navigate("/explore")}
                shimmerColor="#22c55e"
                className="px-10 py-3.5 text-lg font-semibold bg-profit/10 border-profit/40 text-profit hover:shadow-[0_0_30px_rgba(34,197,94,0.4)]"
              >
                Explore FlintTrade
              </ShimmerButton>

              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: step >= 5 ? 1 : 0 }}
                transition={{ delay: 0.3, duration: 1, ease: "easeOut" }}
              >
                <button
                  type="button"
                  onClick={() => navigate("/setup")}
                  className="border border-border-default text-text-primary px-10 py-3.5 rounded-lg text-lg hover:bg-surface-hover hover:border-accent/40 transition-colors duration-150 cursor-pointer"
                >
                  Set Up Workspace
                </button>
              </motion.div>
            </motion.div>
          </div>
        </div>
      </div>
    </>
  );
}
