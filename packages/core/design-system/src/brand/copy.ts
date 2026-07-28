/**
 * Brand copy — the single source of truth for the FlintTrade wordmark and
 * six-word slogan.
 *
 * Every surface that renders the brand reveal (the terminal WelcomeRoute and
 * the public site hero) must import these constants rather than repeating the
 * strings, so the app and the site can never drift apart. The colour names
 * pair one-to-one with the slogan words (Tailwind 400-shade classes in the
 * terminal, nth-child CSS rules on the site) — order is load-bearing.
 */

export const BRAND_WORDMARK = "FlintTrade";

export const BRAND_SLOGAN_WORDS = [
  "Learn",
  "Invest",
  "Trade",
  "Automate",
  "Analyse",
  "Evolve",
] as const;

export const BRAND_SLOGAN_SENTENCE = BRAND_SLOGAN_WORDS.join(". ") + ".";

export const BRAND_SLOGAN_COLOURS = [
  "blue",
  "emerald",
  "amber",
  "rose",
  "purple",
  "cyan",
] as const;
