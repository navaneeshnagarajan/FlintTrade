import { AnimatePresence, motion } from "framer-motion";
import { motionConfig } from "@/lib/motion";

interface PageTransitionProps {
  children: React.ReactNode;
  locationKey: string;
}

/**
 * PageTransition — wraps route content in an opacity-only fade.
 *
 * Design decisions:
 *   - Pure opacity fade only (no y-axis movement). Y-movement creates a
 *     "popup feel" and causes layout shifts on content-heavy routes.
 *   - /trade is skipped entirely — FlexLayout manages its own layout and
 *     panel animations; adding a wrapper would conflict.
 *   - AnimatePresence mode="wait" ensures the exiting page finishes before
 *     the entering page mounts, preventing z-index stacking artifacts.
 *   - Reduced-motion: renders children with no animation wrapper when the
 *     OS accessibility setting is active.
 */
export default function PageTransition({
  children,
  locationKey,
}: PageTransitionProps) {
  // /trade uses FlexLayout — skip the wrapper entirely.
  const isTradeRoute = locationKey === "/trade";

  // Respect OS-level prefers-reduced-motion.
  const reduced = motionConfig.prefersReducedMotion();

  if (isTradeRoute || reduced) {
    return <>{children}</>;
  }

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={locationKey}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={motionConfig.transitions.page}
        // Fill the parent <main> completely so transitions don't affect layout.
        // minHeight/overflow keep Flex-less routes (Home, Settings, …) able to
        // scroll inside <main className="overflow-hidden"> instead of clipping.
        style={{ height: "100%", width: "100%", minHeight: 0, overflow: "hidden" }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
