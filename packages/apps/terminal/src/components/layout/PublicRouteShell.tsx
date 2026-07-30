import { useMemo, type ReactNode } from "react";
import { Link } from "react-router";
import { Moon, Sun, Monitor } from "lucide-react";

import { Meteors } from "@/components/aceternity/meteors";
import { LogoIcon } from "@/components/brand/Logo";
import { Particles } from "@/components/magicui/particles";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ColorMode } from "@/lib/cinematicThemes";
import { useThemeStore } from "@/stores/themeStore";

const widthClass = {
  sm: "max-w-lg",
  md: "max-w-2xl",
  lg: "max-w-4xl",
  xl: "max-w-6xl",
} as const;

interface ThemeModeButtonsProps {
  className?: string;
}

function cssVar(name: string, fallback = ""): string {
  if (typeof window === "undefined") return fallback;
  return (
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() ||
    fallback
  );
}

export function ThemeModeButtons({ className }: ThemeModeButtonsProps) {
  const colorMode = useThemeStore((s) => s.mode);
  const setColorMode = useThemeStore((s) => s.setMode);

  return (
    <div
      className={cn(
        "inline-flex items-center gap-0.5 rounded-full border border-border-default/70 bg-surface-card/70 p-0.5 shadow-lg shadow-black/10 backdrop-blur-xl",
        className,
      )}
      aria-label="Theme mode"
    >
      {(["dark", "light", "system"] as const).map((mode) => {
        const Icon = mode === "dark" ? Moon : mode === "light" ? Sun : Monitor;
        const isActive = colorMode === mode;

        return (
          <Button
            key={mode}
            type="button"
            variant="ghost"
            size="icon-xs"
            onClick={() => setColorMode(mode as ColorMode)}
            aria-label={`Switch to ${mode} mode`}
            className={cn(
              "h-7 w-7 rounded-full",
              isActive
                ? "bg-accent/20 text-accent shadow-[0_0_18px_rgba(34,197,94,0.22)]"
                : "text-text-muted hover:text-text-primary",
            )}
          >
            <Icon className="size-3.5" aria-hidden="true" />
          </Button>
        );
      })}
    </div>
  );
}

interface PublicRouteShellProps {
  mainLabel: string;
  eyebrow?: string;
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  maxWidth?: keyof typeof widthClass;
  className?: string;
  contentClassName?: string;
}

export default function PublicRouteShell({
  mainLabel,
  eyebrow,
  title,
  subtitle,
  actions,
  children,
  maxWidth = "xl",
  className,
  contentClassName,
}: PublicRouteShellProps) {
  const activeThemeId = useThemeStore((s) => s.activeThemeId);
  const particleSettings = useThemeStore((s) => s.getActiveTheme().shared.particles);
  const particleColors = useMemo(
    () => [
      cssVar("--particle-primary", "#22c55e"),
      cssVar("--particle-secondary", "#86efac"),
      cssVar("--particle-tertiary", "#38bdf8"),
    ],
    [activeThemeId],
  );

  return (
    <main
      aria-label={mainLabel}
      className={cn(
        "relative h-screen overflow-x-hidden overflow-y-auto bg-surface-base text-text-primary overscroll-y-contain",
        className,
      )}
    >
      <div className="pointer-events-none fixed inset-0" aria-hidden="true">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_42%,rgba(34,197,94,0.15),transparent_30rem),radial-gradient(circle_at_50%_72%,rgba(56,189,248,0.09),transparent_34rem),linear-gradient(180deg,rgba(8,13,12,0.18),transparent_42%,rgba(0,0,0,0.18))]" />
        <Particles
          quantity={particleSettings.quantity}
          colors={particleColors}
          sizeRange={particleSettings.sizeRange}
          behavior={particleSettings.behavior}
          seed={19_841}
          className="opacity-30"
        />
        <Meteors number={8} seed={8_021} className="opacity-70" />
        <div className="absolute left-1/2 top-1/2 h-[34rem] w-[34rem] -translate-x-1/2 -translate-y-1/2 rounded-full border border-accent/10 shadow-[0_0_120px_rgba(34,197,94,0.11)]" />
      </div>

      <a
        href="#public-main"
        className="sr-only focus:not-sr-only focus:fixed focus:z-100 focus:top-2 focus:left-2 focus:bg-accent focus:text-white focus:px-4 focus:py-2 focus:rounded-md focus:text-sm focus:font-medium focus:shadow-lg"
      >
        Skip to main content
      </a>

      <header className="relative z-40">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
          <Link
            to="/welcome"
            className="flex min-w-0 items-center gap-2 rounded-full border border-border-default/60 bg-surface-card/60 px-3 py-1.5 text-text-secondary shadow-lg shadow-black/10 backdrop-blur-xl transition-colors hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <LogoIcon size={20} aria-hidden="true" />
            <span className="font-heading text-sm font-semibold">FlintTrade</span>
          </Link>

          <div className="flex min-w-0 items-center gap-2">
            {actions}
            <ThemeModeButtons className="hidden sm:inline-flex" />
          </div>
        </div>
      </header>

      <div
        id="public-main"
        tabIndex={-1}
        className={cn(
          "relative z-10 mx-auto flex min-h-[calc(100vh-4rem)] w-full flex-col items-center justify-center px-4 py-8 text-center outline-none sm:px-6 sm:py-10",
          widthClass[maxWidth],
          contentClassName,
        )}
      >
        {(eyebrow || title || subtitle) && (
          <section className="mx-auto mb-7 max-w-3xl space-y-3">
            {eyebrow && (
              <p className="text-xxs font-semibold uppercase tracking-[0.32em] text-accent/80">
                {eyebrow}
              </p>
            )}
            {title && (
              <h1 className="font-heading text-3xl font-bold text-text-primary drop-shadow-[0_0_28px_rgba(34,197,94,0.16)] sm:text-5xl">
                {title}
              </h1>
            )}
            {subtitle && (
              <p className="mx-auto max-w-2xl text-sm leading-relaxed text-text-secondary sm:text-base">
                {subtitle}
              </p>
            )}
          </section>
        )}

        <div className="w-full">{children}</div>
      </div>
    </main>
  );
}
