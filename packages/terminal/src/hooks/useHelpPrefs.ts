import { useSkillStore } from "@/stores/skillStore";
import type { HelpPrefs } from "@/types/skill";

export function useHelpPrefs(): HelpPrefs {
  return useSkillStore((s) => s.helpPrefs);
}
