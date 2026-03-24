import { useCallback } from "react";
import { useSkillStore } from "@/stores/skillStore";
import type { Domain } from "@/types/skill";

export function useTrackBehavior() {
  const trackAction = useSkillStore((s) => s.trackAction);
  return useCallback(
    (domain: Domain, action: string) => trackAction(domain, action),
    [trackAction]
  );
}
