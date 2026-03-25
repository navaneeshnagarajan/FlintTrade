/**
 * Shared animation tokens and presets for FlintTrade.
 *
 * Usage:
 *   import { motionConfig } from "@/lib/motion";
 *   import type { AnimationVariants } from "@/lib/motion";
 *
 *   <motion.div variants={motionConfig.variants.fadeIn} ... />
 *   transition={motionConfig.transitions.page}
 *
 * All easing arrays are `as const` tuples — Framer Motion accepts
 * [x1, y1, x2, y2] cubic-bezier format directly.
 *
 * Rules:
 *   - Never use ease-in for UI (feels sluggish entering).
 *   - Enter: overshooting deceleration curve (fast start, soft land).
 *   - Move:  balanced deceleration (smooth repositioning).
 *   - Exit:  fast acceleration (element leaves decisively).
 *   - Standard: balanced in-out (micro-interactions, toggles).
 */

import type { Variants, Transition } from "framer-motion";

// ---------------------------------------------------------------------------
// Easing curves
// ---------------------------------------------------------------------------

/**
 * Enter curve — overshooting deceleration. Elements arrive with energy.
 * CSS equivalent: cubic-bezier(0.22, 1, 0.36, 1)
 */
export const EASE_ENTER = [0.22, 1, 0.36, 1] as const;

/**
 * Move curve — balanced deceleration. Elements reposition smoothly.
 * CSS equivalent: cubic-bezier(0.25, 1, 0.5, 1)
 */
export const EASE_MOVE = [0.25, 1, 0.5, 1] as const;

/**
 * Exit curve — fast acceleration out. Elements leave decisively.
 * CSS equivalent: cubic-bezier(0.4, 0, 1, 1)
 */
export const EASE_EXIT = [0.4, 0, 1, 1] as const;

/**
 * Standard curve — balanced in-out. For micro-interactions and toggles.
 * CSS equivalent: cubic-bezier(0.4, 0, 0.2, 1)
 */
export const EASE_STANDARD = [0.4, 0, 0.2, 1] as const;

// TypeScript type for all easing tuples
export type EaseTuple = readonly [number, number, number, number];

// ---------------------------------------------------------------------------
// Duration tokens (seconds)
// ---------------------------------------------------------------------------

export const DURATION = {
  /** 0.1s — immediate feedback, button presses, hover states */
  instant: 0.1,
  /** 0.15s — fast micro-animations, icon swaps, badge updates */
  fast: 0.15,
  /** 0.2s — standard UI transitions, panels, tooltips */
  normal: 0.2,
  /** 0.35s — deliberate transitions, drawers, modals */
  slow: 0.35,
  /** 0.6s — cinematic sequences, route changes, onboarding */
  cinematic: 0.6,
} as const;

export type DurationToken = keyof typeof DURATION;

// ---------------------------------------------------------------------------
// Transition presets
// ---------------------------------------------------------------------------

/** Full-page route transition — cinematic, enter curve */
const transitionPage: Transition = {
  duration: DURATION.cinematic,
  ease: EASE_ENTER,
};

/** Tab / panel switch — fast, enter curve */
const transitionTab: Transition = {
  duration: DURATION.normal,
  ease: EASE_ENTER,
};

/** Opacity-only fade — standard curve, normal speed */
const transitionFade: Transition = {
  duration: DURATION.normal,
  ease: EASE_STANDARD,
};

/** Scale pop — fast enter for menus, dropdowns, tooltips */
const transitionScale: Transition = {
  duration: DURATION.fast,
  ease: EASE_ENTER,
};

// ---------------------------------------------------------------------------
// Animation variants
// ---------------------------------------------------------------------------

/** Fade in from transparent, fade out to transparent */
const variantsFadeIn: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: transitionFade },
  exit: { opacity: 0, transition: { duration: DURATION.fast, ease: EASE_EXIT } },
};

/** Slide up from below while fading in (list items, cards, widgets) */
const variantsSlideUp: Variants = {
  initial: { opacity: 0, y: 16 },
  animate: {
    opacity: 1,
    y: 0,
    transition: { duration: DURATION.slow, ease: EASE_ENTER },
  },
  exit: {
    opacity: 0,
    y: 8,
    transition: { duration: DURATION.fast, ease: EASE_EXIT },
  },
};

/** Scale in from slightly smaller, used for modals, popovers, menus */
const variantsScaleIn: Variants = {
  initial: { opacity: 0, scale: 0.96 },
  animate: {
    opacity: 1,
    scale: 1,
    transition: { duration: DURATION.normal, ease: EASE_ENTER },
  },
  exit: {
    opacity: 0,
    scale: 0.96,
    transition: { duration: DURATION.fast, ease: EASE_EXIT },
  },
};

// ---------------------------------------------------------------------------
// Stagger helper
// ---------------------------------------------------------------------------

/**
 * Returns a Framer Motion transition with a staggered delay based on index.
 *
 * @param index     — zero-based position in the list
 * @param base      — base transition to extend (defaults to slideUp's animate transition)
 * @param step      — seconds of delay added per index step (default: 0.06s)
 * @param maxIndex  — items at index >= maxIndex render instantly (delay: 0).
 *                    Prevents excessive delay for long lists. Default: 8.
 *
 * @example
 *   items.map((item, i) => (
 *     <motion.div
 *       key={item.id}
 *       variants={motionConfig.variants.slideUp}
 *       transition={motionConfig.stagger(i)}
 *     />
 *   ))
 */
function stagger(
  index: number,
  base: Transition = { duration: DURATION.slow, ease: EASE_ENTER },
  step = 0.06,
  maxIndex = 8,
): Transition {
  if (index >= maxIndex) {
    return { ...base, delay: 0 };
  }
  return {
    ...base,
    delay: index * step,
  };
}

// ---------------------------------------------------------------------------
// Reduced-motion check
// ---------------------------------------------------------------------------

/**
 * Returns true when the user has requested reduced motion via OS/browser setting.
 * Components should skip or simplify animations when this returns true.
 *
 * @example
 *   const shouldAnimate = !motionConfig.prefersReducedMotion();
 */
function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  if (typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

// ---------------------------------------------------------------------------
// Exported types
// ---------------------------------------------------------------------------

export type AnimationVariants = Variants;

export interface MotionTransitions {
  page: Transition;
  tab: Transition;
  fade: Transition;
  scale: Transition;
}

export interface MotionVariants {
  fadeIn: Variants;
  slideUp: Variants;
  scaleIn: Variants;
}

export interface MotionConfig {
  ease: {
    enter: EaseTuple;
    move: EaseTuple;
    exit: EaseTuple;
    standard: EaseTuple;
  };
  duration: typeof DURATION;
  transitions: MotionTransitions;
  variants: MotionVariants;
  stagger: typeof stagger;
  prefersReducedMotion: typeof prefersReducedMotion;
}

// ---------------------------------------------------------------------------
// Single export object
// ---------------------------------------------------------------------------

export const motionConfig: MotionConfig = {
  ease: {
    enter: EASE_ENTER,
    move: EASE_MOVE,
    exit: EASE_EXIT,
    standard: EASE_STANDARD,
  },
  duration: DURATION,
  transitions: {
    page: transitionPage,
    tab: transitionTab,
    fade: transitionFade,
    scale: transitionScale,
  },
  variants: {
    fadeIn: variantsFadeIn,
    slideUp: variantsSlideUp,
    scaleIn: variantsScaleIn,
  },
  stagger,
  prefersReducedMotion,
};
