import { useLayoutEffect, useRef } from "react";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { DURATION, EASE_ENTER } from "@/lib/motion";
import { useThemeStore } from "@/stores/themeStore";

interface TabTransitionProps {
  /** Active tab identifier — changes mount the next panel immediately. */
  tabKey: string;
  children: React.ReactNode;
  className?: string;
}

const FADE_OPTIONS: KeyframeAnimationOptions = {
  duration: DURATION.normal * 1000,
  easing: `cubic-bezier(${EASE_ENTER.join(",")})`,
  fill: "none",
};

/**
 * Fade route/tab content without making its lifetime depend on motion policy.
 * Only a new tabKey replaces the panel; a live preference change cancels the
 * fade, not the child's local state. Content and ARIA selection never wait for
 * an exit animation. The unanimated DOM is visible, including without WAAPI.
 */
export default function TabTransition({ tabKey, children, className }: TabTransitionProps) {
  const wrapper = useRef<HTMLDivElement>(null);
  // The application root uses reducedMotion="user". Keep that OS policy
  // reactive, with the app's explicit reduction preference taking precedence.
  const osReducedMotion = usePrefersReducedMotion();
  const appReducedMotion = useThemeStore(state => state.reduceMotion);
  const reducedMotion = osReducedMotion || appReducedMotion;

  useLayoutEffect(() => {
    const node = wrapper.current;
    if (reducedMotion || !node?.animate) return;

    // No style mutation, forced layout, frame loop or finished-promise to own.
    // Cancelling (including on reduced motion) reveals the visible base style.
    let fade: Animation;
    try {
      fade = node.animate([{ opacity: 0 }, { opacity: 1 }], FADE_OPTIONS);
    } catch {
      // Older/partial native implementations must leave the panel usable.
      return;
    }
    return () => fade.cancel();
  }, [tabKey, reducedMotion]);

  return <div key={tabKey} ref={wrapper} className={className}>{children}</div>;
}
