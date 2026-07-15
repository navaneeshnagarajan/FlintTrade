import type { ReactNode } from "react";
import { useAuthGuard } from "@/hooks/useAuthGuard";

function ProtectedLoading() {
  return (
    <div className="flex h-screen items-center justify-center bg-background" role="status">
      <div className="flex flex-col items-center gap-3">
        <div className="size-8 animate-spin rounded-full border-2 border-accent/30 border-t-accent" />
        <p className="animate-pulse text-sm text-muted">Loading FlintTrade...</p>
      </div>
    </div>
  );
}

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuthGuard();
  if (isLoading) return <ProtectedLoading />;
  if (!isAuthenticated) return null;
  return <>{children}</>;
}
