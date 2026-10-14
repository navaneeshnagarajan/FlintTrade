import { useAuthStore } from "@/stores/authStore";
export function LogoutNotice() {
  const result = useAuthStore(state => state.logoutResult);
  const status = useAuthStore(state => state.status);
  if (!result || status !== "logged-out") return null;
  const message = result.state === "confirmed" ? "Local UI session ended. Server confirmed retirement of the original session."
    : result.state === "pending" ? "Local UI session ended. Server revocation is pending."
    : `Local UI session ended. Server revocation is not confirmed${result.code ? ` (${result.code})` : ""}. Do not assume the original server credential or remote activity was retired.`;
  return <div role={result.state === "unconfirmed" || result.state === "local-only" ? "alert" : "status"} className="border-b border-border-default bg-surface-card p-3 text-sm">{message}</div>;
}
