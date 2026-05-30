"use client";

// DesignSystemProvider (HI38 density + L5 locale contract).
//
// Mirrors the chosen density into a `data-density` attribute on <html> so the CSS
// custom-property cascade (--row-height, --cell-padding-y, …) responds without forcing
// a re-render on every consumer. Primitives that expose a `density` cva variant read
// DensityContext; apps with no provider fall back to "comfortable" (graceful CSS-cascade
// fallback per DS-PROV-08), so primitives always render.

import * as React from "react";

export type Density = "compact" | "comfortable";

interface DensityContextValue {
  density: Density;
}

export const DensityContext = React.createContext<DensityContextValue>({
  density: "comfortable",
});

interface DesignSystemProviderProps {
  density?: Density;
  /**
   * Reserved for future i18n — accepted today but no-op (see §11).
   * Marked `readonly` (L5): the contract guarantees the prop is never mutated by the
   * provider and never consulted at runtime in v1.0. Consumers that destructure
   * {locale} from DensityContext get undefined — locale is deliberately absent from the
   * context value object. When i18n lands a `useTranslation()` hook reads from here
   * (an additive change).
   */
  readonly locale?: string;
  children: React.ReactNode;
}

export function DesignSystemProvider({
  density = "comfortable",
  locale, // intentionally unused in v1.0 (L5)
  children,
}: DesignSystemProviderProps) {
  void locale;
  React.useEffect(() => {
    document.documentElement.setAttribute("data-density", density);
    return () => {
      // Do NOT remove on unmount in production — the provider lives at the root.
      // Only relevant for tests, where we want the attribute to disappear when the
      // provider is torn down.
      if (process.env.NODE_ENV === "test") {
        document.documentElement.removeAttribute("data-density");
      }
    };
  }, [density]);

  const value = React.useMemo(() => ({ density }), [density]);
  return <DensityContext.Provider value={value}>{children}</DensityContext.Provider>;
}
