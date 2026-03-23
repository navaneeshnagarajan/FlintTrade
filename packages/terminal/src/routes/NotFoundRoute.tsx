/**
 * NotFoundRoute — 404 catch-all page at path "*".
 *
 * Shown when the user navigates to a route that does not exist.
 * Provides two escape hatches: Go Home (/) and Explore (/explore).
 */

import { useNavigate } from "react-router-dom";
import { LogoIcon } from "@/components/brand/Logo";
import { BlurFade } from "@/components/magicui/blur-fade";

export default function NotFoundRoute() {
  const navigate = useNavigate();

  return (
    <main aria-label="Page not found" className="fixed inset-0 bg-surface-base flex items-center justify-center p-6 overflow-y-auto">
      <BlurFade delay={0} duration={0.4}>
        <div className="max-w-md w-full text-center space-y-6">
          {/* Logo */}
          <div className="flex justify-center">
            <LogoIcon size={40} className="text-text-muted" />
          </div>

          {/* Status code */}
          <BlurFade delay={0.1} duration={0.4}>
            <div className="space-y-2">
              <p className="font-heading font-bold text-text-disabled text-7xl tracking-tight select-none">
                404
              </p>
              <h1 className="font-heading font-bold text-text-primary text-xl">
                Page not found
              </h1>
              <p className="text-text-muted text-sm leading-relaxed">
                The page you&apos;re looking for doesn&apos;t exist.
              </p>
            </div>
          </BlurFade>

          {/* Actions */}
          <BlurFade delay={0.2} duration={0.4}>
            <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
              <button
                type="button"
                onClick={() => navigate("/")}
                className="w-full sm:w-auto px-6 py-2 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary/90 transition-colors cursor-pointer"
              >
                Go Home
              </button>
              <button
                type="button"
                onClick={() => navigate("/explore")}
                className="w-full sm:w-auto px-6 py-2 rounded-lg border border-border-default bg-surface-elevated text-text-primary text-sm font-medium hover:bg-surface-hover transition-colors cursor-pointer"
              >
                Explore
              </button>
            </div>
          </BlurFade>
        </div>
      </BlurFade>
    </main>
  );
}
