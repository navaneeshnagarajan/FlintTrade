/**
 * NotFoundRoute — 404 catch-all page at path "*".
 *
 * Shown when the user navigates to a route that does not exist.
 * Offers Home, back to where they were, and the example-data demo.
 */

import { useNavigate } from "react-router";
import { LogoIcon } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";

export default function NotFoundRoute() {
  const navigate = useNavigate();

  return (
    <main aria-label="Page not found" className="fixed inset-0 bg-surface-base flex items-center justify-center p-6 overflow-y-auto">
      <div className="max-w-md w-full text-center space-y-6 animate-fade-in">
          {/* Logo */}
          <div className="flex justify-center">
            <LogoIcon size={40} className="text-text-muted" />
          </div>

          {/* Status code */}
          <div className="space-y-2">
              <p className="font-heading font-bold text-text-muted text-6xl tracking-tight select-none" aria-hidden="true">
                404
              </p>
              <h1 className="font-heading font-semibold text-text-primary text-xl">
                Page not found
              </h1>
              <p className="text-text-secondary text-sm leading-relaxed">
                This address does not match any page in FlintTrade. It may have moved, or the link may be mistyped.
              </p>
          </div>

          {/* Actions */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
              <Button onClick={() => navigate("/")} className="w-full sm:w-auto">
                Go Home
              </Button>
              <Button variant="outline" onClick={() => navigate(-1)} className="w-full sm:w-auto">
                Go back
              </Button>
              <Button variant="ghost" onClick={() => navigate("/explore")} className="w-full sm:w-auto">
                Demo (example data)
              </Button>
          </div>
      </div>
    </main>
  );
}
