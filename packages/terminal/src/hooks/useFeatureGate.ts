import { useSkillLevel } from "./useSkillLevel";
import { FEATURE_GATES } from "@/lib/featureGates";
import type { Domain } from "@/types/skill";

export type GateStatus = "visible" | "preview" | "locked";

/** Returns gate status for a feature based on current skill level. */
export function useFeatureGate(featureId: string, domain?: Domain): GateStatus {
  const level = useSkillLevel(domain);
  const gate = FEATURE_GATES[featureId];
  if (!gate) return "visible"; // unknown features default to visible
  return gate[level];
}
