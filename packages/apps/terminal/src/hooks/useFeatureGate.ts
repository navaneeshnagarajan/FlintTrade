import type { Domain } from "@/types/skill";
export type GateStatus = "visible" | "preview" | "locked";
/** Discovery is open. Runtime readiness and authority remain independent. */
export function useFeatureGate(_featureId: string, _domain?: Domain): GateStatus {
  return "visible";
}
