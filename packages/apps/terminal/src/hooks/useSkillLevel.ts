import { useSkillStore } from "@/stores/skillStore";
import type { SkillLevel, Domain } from "@/types/skill";

/** Returns effective skill level for the given domain (or global if no domain). */
export function useSkillLevel(domain?: Domain): SkillLevel {
  const getEffective = useSkillStore((s) => s.getEffectiveLevel);
  const globalLevel = useSkillStore((s) => s.globalLevel);
  return domain ? getEffective(domain) : globalLevel;
}
