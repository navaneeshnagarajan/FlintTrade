/**
 * NotifyMe.tsx
 *
 * A CTA button: "Notify me when live"
 *
 * Behaviour:
 *   - Uses ShimmerButton for the primary CTA
 *   - On click: writes { featureName, channel, timestamp } to localStorage
 *     key `ft-notify-prefs` (appends; never overwrites others)
 *   - After click: shows "Subscribed" in green with a check icon; disables button
 *   - On mount: reads localStorage — if already subscribed, shows confirmed state
 *
 * Accessibility:
 *   - aria-live region announces subscription confirmation
 *   - Button has descriptive aria-label
 *   - Focus ring follows shadcn/ui ring token
 */

import { useState, useEffect } from "react";
import { Send, CheckCircle2 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { ShimmerButton } from "@/components/magicui/shimmer-button";
import { cn } from "@/lib/utils";
import { DURATION, EASE_ENTER } from "@/lib/motion";
import {
  NOTIFY_PREFS_KEY,
  type NotifyPref,
  type TeaserConfig,
} from "./types";

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

function readPrefs(): NotifyPref[] {
  try {
    const raw = localStorage.getItem(NOTIFY_PREFS_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed as NotifyPref[];
  } catch {
    // ignore
  }
  return [];
}

function isSubscribed(featureName: string): boolean {
  return readPrefs().some((p) => p.featureName === featureName);
}

function writePref(pref: NotifyPref): void {
  try {
    const existing = readPrefs().filter(
      (p) => p.featureName !== pref.featureName,
    );
    localStorage.setItem(
      NOTIFY_PREFS_KEY,
      JSON.stringify([...existing, pref]),
    );
  } catch {
    // ignore storage quota errors
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface NotifyMeProps {
  config: Pick<TeaserConfig, "featureName" | "notifyChannel">;
  className?: string;
}

export function NotifyMe({ config, className }: NotifyMeProps) {
  const { featureName, notifyChannel = "telegram" } = config;

  const [subscribed, setSubscribed] = useState<boolean>(() =>
    isSubscribed(featureName),
  );

  // Re-sync if featureName changes (e.g. reused component)
  useEffect(() => {
    setSubscribed(isSubscribed(featureName));
  }, [featureName]);

  function handleSubscribe() {
    if (subscribed) return;
    const pref: NotifyPref = {
      featureName,
      channel: notifyChannel,
      timestamp: Date.now(),
    };
    writePref(pref);
    setSubscribed(true);
  }

  return (
    <div className={cn("flex flex-col items-start gap-1.5", className)}>
      <AnimatePresence mode="wait">
        {subscribed ? (
          <motion.div
            key="subscribed"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{
              opacity: 1,
              scale: 1,
              transition: { duration: DURATION.normal, ease: EASE_ENTER },
            }}
            exit={{ opacity: 0, transition: { duration: DURATION.fast } }}
            role="status"
            aria-live="polite"
            aria-atomic="true"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium",
              "bg-emerald-400/10 border border-emerald-400/20 text-emerald-400",
            )}
          >
            <CheckCircle2 size={12} aria-hidden="true" />
            <span>Subscribed</span>
          </motion.div>
        ) : (
          <motion.div
            key="cta"
            initial={{ opacity: 0 }}
            animate={{
              opacity: 1,
              transition: { duration: DURATION.fast },
            }}
            exit={{ opacity: 0, transition: { duration: DURATION.fast } }}
          >
            <ShimmerButton
              onClick={handleSubscribe}
              shimmerColor="#3b82f6"
              className="text-xs px-3 py-1.5 h-auto"
              aria-label={`Notify me when ${featureName} is live`}
            >
              <Send size={11} aria-hidden="true" />
              <span>Notify me when live</span>
            </ShimmerButton>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Post-subscribe disclaimer */}
      {subscribed && (
        <p className="text-xs text-text-muted mt-1">
          Preference saved locally. Configure Telegram in Settings for push notifications.
        </p>
      )}

      {/* Channel hint */}
      {!subscribed && (
        <span className="text-[10px] text-text-muted pl-0.5">
          via {notifyChannel === "telegram" ? "Telegram" : "email"}
        </span>
      )}
    </div>
  );
}

export default NotifyMe;
