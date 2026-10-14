import type { Domain, SkillLevel } from "@/types/skill";

/** Compatibility for existing presentations. Experience no longer restricts
 * discovery. This value confers NO account, broker or execution authority. */
export function useSkillLevel(_domain?: Domain): SkillLevel {
  return "advanced";
}
