import { AnimatePresence, motion } from "framer-motion";
import { motionConfig } from "@/lib/motion";

interface TabTransitionProps {
  /** Active tab identifier — changes trigger the crossfade transition */
  tabKey: string;
  children: React.ReactNode;
  className?: string;
}

/**
 * Crossfade wrapper for sidebar/tab content switches within routes.
 *
 * Used by /invest, /learn, /lab, /automate, /ai when switching between
 * their internal tabs. Respects prefers-reduced-motion — renders children
 * without any animation wrapper when the user has opted out of motion.
 */
export default function TabTransition({
  tabKey,
  children,
  className,
}: TabTransitionProps) {
  if (motionConfig.prefersReducedMotion()) {
    return <>{children}</>;
  }

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={tabKey}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={motionConfig.transitions.tab}
        className={className}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
