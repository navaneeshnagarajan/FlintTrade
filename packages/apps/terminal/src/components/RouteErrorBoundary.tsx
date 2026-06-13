/**
 * RouteErrorBoundary — per-route error isolation.
 *
 * Wraps individual route content so a crash in one route (e.g. /invest)
 * doesn't kill the entire app shell (TopBar, TickerBar). The user can
 * reload or navigate to another route without losing the shell.
 */

import { Component } from "react";
import type { ReactNode, ErrorInfo } from "react";
import { LogoIcon } from "@/components/brand/Logo";
import { reportError } from "@/services/errorReporter";

interface Props {
  children: ReactNode;
  routeName?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class RouteErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    const routeName = this.props.routeName ?? "Route";
    console.error(`[RouteErrorBoundary] ${routeName} crashed:`, error, info.componentStack);

    // Report to Glitchtip via backend and Sentry SDK (if DSN configured).
    void reportError(error, {
      route: routeName,
      componentStack: info.componentStack ?? undefined,
      boundary: "RouteErrorBoundary",
    });

    if (import.meta.env.VITE_GLITCHTIP_DSN) {
      import("@sentry/react").then((Sentry) => {
        Sentry.captureException(error, {
          extra: { route: routeName, componentStack: info.componentStack },
        });
      }).catch(() => undefined);
    }
  }

  private handleReload = (): void => {
    this.setState({ hasError: false, error: null });
  };

  private handleGoHome = (): void => {
    // Honour Vite's base so subpath hosting (e.g. /demo-app/) stays inside the app.
    window.location.href = import.meta.env.BASE_URL;
  };

  override render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    const message = this.state.error?.message ?? "An unknown error occurred.";
    const truncated = message.length > 200 ? `${message.slice(0, 200)}…` : message;
    const route = this.props.routeName ?? "This page";

    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="max-w-md w-full rounded-xl border border-border-default bg-surface-card p-8 text-center space-y-5">
          <div className="flex justify-center">
            <LogoIcon size={36} className="text-text-muted" />
          </div>

          <div className="space-y-2">
            <h1 className="font-heading font-bold text-text-primary text-xl">
              {route} encountered an error
            </h1>
            <p className="text-text-muted text-sm leading-relaxed">
              The rest of the app is still working. Try again or navigate to another page.
            </p>
          </div>

          {truncated && (
            <div className="rounded-lg bg-surface-base border border-border-subtle px-4 py-3 text-left">
              <p className="text-xs font-mono text-loss leading-relaxed break-all">
                {truncated}
              </p>
            </div>
          )}

          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-1">
            <button
              type="button"
              onClick={this.handleReload}
              className="w-full sm:w-auto px-6 py-2 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary/90 transition-colors cursor-pointer"
            >
              Try Again
            </button>
            <button
              type="button"
              onClick={this.handleGoHome}
              className="w-full sm:w-auto px-6 py-2 rounded-lg border border-border-default bg-surface-elevated text-text-primary text-sm font-medium hover:bg-surface-hover transition-colors cursor-pointer"
            >
              Go Home
            </button>
          </div>
        </div>
      </div>
    );
  }
}
