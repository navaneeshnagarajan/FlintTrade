import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { useAuthStore, captureAuthSessionFence, isAuthSessionFenceCurrent } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { buildHeaders, getBase } from "@/services/ftApi.helpers";
const Record = z.record(z.string(), z.unknown());
const Snapshot = z.looseObject({ schema_version: z.literal(1), observed_at: z.string(), scope: z.literal("core_process"), resources: Record, acquisition: Record, models: Record, jobs: Record, network_diagnosis: Record, operational_events: Record, recovery: Record });
export function useSystemDiagnostics() {
  const authenticated = useAuthStore(s => s.status === "logged-in");
  const mode = useModeStore(s => s.mode);
  return useQuery({ queryKey: ["system", "diagnostics"], enabled: authenticated && mode !== "explore", staleTime: 25_000, refetchInterval: 30_000, retry: false, queryFn: async ({ signal }) => {
    const fence = captureAuthSessionFence();
    const response = await fetch(`${getBase()}/api/v1/system/diagnostics`, { method: "GET", headers: buildHeaders(false), signal, cache: "no-store" });
    if (!response.ok) throw new Error(`Diagnostics unavailable (${response.status})`);
    const body: unknown = await response.json();
    if (!isAuthSessionFenceCurrent(fence)) throw new Error("Diagnostics belong to a retired session");
    return z.object({ status: z.literal("success"), data: Snapshot }).parse(body).data;
  } });
}
