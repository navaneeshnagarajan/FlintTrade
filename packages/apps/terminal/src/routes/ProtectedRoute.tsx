import type { ReactNode } from "react";
import { useAuthGuard } from "@/hooks/useAuthGuard";

function ProtectedLoading({ message }: { message: string }) {
  return (
    <div className="flex h-screen items-center justify-center bg-surface-base" role="status">
      <div className="flex flex-col items-center gap-3">
        <div className="size-8 animate-spin rounded-full border-2 border-accent/30 border-t-accent" />
        <p className="animate-pulse text-sm text-text-muted">{message}</p>
      </div>
    </div>
  );
}

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuthGuard();
  if (isLoading) return <ProtectedLoading message="Loading FlintTrade..." />;
  // Keep account-owning children unmounted, but never leave a blank page while
  // the guard redirects to /welcome — that looked like a hung or broken app.
  if (!isAuthenticated) {
    return <ProtectedLoading message="Redirecting to welcome…" />;
  }
  return <>{children}</>;
}
