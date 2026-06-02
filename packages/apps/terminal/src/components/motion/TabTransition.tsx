import { motion } from "framer-motion";
import { motionConfig } from "@/lib/motion";

interface TabTransitionProps {
  /** Active tab identifier — changes trigger the crossfade transition */
  tabKey: string;
  children: React.ReactNode;
  className?: string;
}

/**
 * Fade wrapper for sidebar/tab content switches within routes.
 *
 * Used by /invest, /learn, /lab, /automate, /ai when switching between
 * their internal tabs. Respects prefers-reduced-motion — renders children
 * without any animation wrapper when the user has opted out of motion.
 *
 * The keyed motion node mounts the new panel immediately. That keeps ARIA tab
 * state and visible panel content in sync even when a tab's lazy chunk is still
 * resolving.
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
    <motion.div
      key={tabKey}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={motionConfig.transitions.tab}
      className={className}
    >
      {children}
    </motion.div>
  );
}
