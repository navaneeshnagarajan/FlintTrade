/**
 * Brand reveal timeline — the single source of truth for the cinematic
 * intro's millisecond schedule.
 *
 * The public site's hero animation (CSS keyframe delays in the site's
 * globals.css) and the terminal WelcomeRoute's step machine must both derive
 * from this timeline so the two reveals stay frame-matched:
 *
 *   t=1.00s fireball strike begins
 *   t=2.00s impact blast, shock rings, debris
 *   t=2.20s logo spring reveal (~900ms overshoot)
 *   t=3.28s wordmark character cascade (520ms per char, 45ms stagger)
 *   t=4.20s slogan word colour cascade (500ms per word, 55ms stagger)
 *   t=5.08s description, feature chips, CTAs
 */

export const BRAND_REVEAL_TIMELINE = {
  /** Cinematic sequence kick-off (fireball strike begins). */
  sequenceStartMs: 1000,
  /** Impact blast, shock rings, and debris burst. */
  impactMs: 2000,
  /** Logo spring reveal start. */
  logoMs: 2200,
  /** Approximate settle time of the logo spring (stiffness 120, damping 28). */
  logoSpringMs: 900,
  /** Wordmark character cascade start. */
  wordmarkMs: 3280,
  /** Duration of each wordmark character's entrance. */
  wordmarkCharMs: 520,
  /** Stagger between successive wordmark characters. */
  wordmarkStaggerMs: 45,
  /** Slogan word colour cascade start. */
  sloganMs: 4200,
  /** Duration of each slogan word's entrance. */
  sloganWordMs: 500,
  /** Stagger between successive slogan words. */
  sloganStaggerMs: 55,
  /** Description, feature chips, and CTAs reveal. */
  contentMs: 5080,
} as const;
