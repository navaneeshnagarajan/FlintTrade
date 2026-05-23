/**
 * ErrorBoundary — catches React render errors and shows a recovery UI.
 *
 * Wraps the entire app in main.tsx so a widget or route crash cannot
 * take down the whole application. Provides "Reload" and "Go Home"
 * escape hatches so users are never stuck on a blank screen.
 */

import { Component } from "react";
import type { ReactNode, ErrorInfo } from "react";
import { LogoIcon } from "@/components/brand/Logo";
import { reportError } from "@/services/errorReporter";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[ErrorBoundary] Uncaught render error:", error, info.componentStack);

    // Report to Glitchtip via backend and Sentry SDK (if DSN configured).
    void reportError(error, { componentStack: info.componentStack ?? undefined, boundary: "ErrorBoundary" });

    // Forward to Sentry SDK when it has been initialised.
    if (import.meta.env.VITE_GLITCHTIP_DSN) {
      import("@sentry/react").then((Sentry) => {
        Sentry.captureException(error, { extra: { componentStack: info.componentStack } });
      }).catch(() => undefined);
    }
  }

  private handleReload = (): void => {
    window.location.reload();
  };

  private handleGoHome = (): void => {
    window.location.href = "/";
  };

  override render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    // Custom fallback takes priority
    if (this.props.fallback) {
      return this.props.fallback;
    }

    const message = this.state.error?.message ?? "An unknown error occurred.";
    const truncated = message.length > 200 ? `${message.slice(0, 200)}…` : message;

    return (
      <div className="fixed inset-0 bg-surface-base flex items-center justify-center p-6">
        <div className="max-w-md w-full rounded-xl border border-border-default bg-surface-card p-8 text-center space-y-5">
          {/* Logo */}
          <div className="flex justify-center">
            <LogoIcon size={36} className="text-text-muted" />
          </div>

          {/* Heading */}
          <div className="space-y-2">
            <h1 className="font-heading font-bold text-text-primary text-xl">
              Something went wrong
            </h1>
            <p className="text-text-muted text-sm leading-relaxed">
              A component encountered an unexpected error. Your work is safe — reload to continue.
            </p>
          </div>

          {/* Error detail */}
          {truncated && (
            <div className="rounded-lg bg-surface-base border border-border-subtle px-4 py-3 text-left">
              <p className="text-xs font-mono text-loss leading-relaxed break-all">
                {truncated}
              </p>
            </div>
          )}

          {/* Actions */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-1">
            <button
              type="button"
              onClick={this.handleReload}
              className="w-full sm:w-auto px-6 py-2 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary/90 transition-colors cursor-pointer"
            >
              Reload
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
