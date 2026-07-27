import { useLayoutStore } from "@/stores/layoutStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { useSkillStore } from "@/stores/skillStore";
import { normaliseLlmHost, providerSelection } from "@/lib/llmProviders";
import type { Domain, SkillLevel } from "@/types/skill";

import type { ConnectionFormValues } from "./connectionForm";
import type { Persona, ExperienceLevel } from "./PersonaStep";
import { getPresetName, mapWizardPreset } from "./ReviewStep";
import type { RiskFormValues } from "./RiskStep";
import type { TradingDefaultsFormValues } from "./TradingStep";

export interface SetupChoices {
  persona: Persona;
  experience?: ExperienceLevel | null;
  connection?: Partial<ConnectionFormValues> | null;
  tradingDefaults?: Partial<TradingDefaultsFormValues> | null;
  riskLimits?: Partial<RiskFormValues> | null;
  llm?: { provider: string; model: string; host?: string } | null;
  name?: string;
  interests?: string[];
}

export function personaRoute(persona: Persona): string {
  if (persona === "investor") return "/invest";
  if (persona === "beginner") return "/learn";
  return "/trade";
}

export function defaultExperienceForPersona(persona: Persona): ExperienceLevel {
  return persona === "beginner" ? "new" : "intermediate";
}

export function mapExperience(level: ExperienceLevel | null): "beginner" | "intermediate" | "pro" | "custom" {
  if (level === "new") return "beginner";
  if (level === "professional") return "pro";
  return "intermediate";
}

/**
 * Maps wizard persona + experience to skillStore levels.
 * Returns globalLevel and optional per-domain overrides.
 */
export function deriveSkillLevels(
  persona: Persona,
  experience: ExperienceLevel | null,
): { globalLevel: SkillLevel; overrides: Partial<Record<Domain, SkillLevel>> } {
  if (persona === "beginner") {
    return { globalLevel: "beginner", overrides: {} };
  }
  if (persona === "trader") {
    if (experience === "new" || experience === null) {
      return { globalLevel: "beginner", overrides: {} };
    }
    if (experience === "intermediate") {
      return { globalLevel: "intermediate", overrides: {} };
    }
    return { globalLevel: "advanced", overrides: {} };
  }
  if (experience === "new" || experience === null) {
    return { globalLevel: "beginner", overrides: { invest: "intermediate" } };
  }
  if (experience === "intermediate") {
    return { globalLevel: "intermediate", overrides: {} };
  }
  return { globalLevel: "intermediate", overrides: { invest: "advanced" } };
}

export function persistSetupChoices(choices: SetupChoices): string {
  const persona = choices.persona;
  const experience = choices.experience ?? defaultExperienceForPersona(persona);
  const interests = choices.interests ?? [];

  useSettingsStore.getState().setPersona(persona);
  useSettingsStore.getState().setName(choices.name || "Trader");
  useSettingsStore.getState().setInterests(interests);
  useSettingsStore.getState().setExperience(mapExperience(experience));

  const { globalLevel, overrides } = deriveSkillLevels(persona, experience);
  useSkillStore.getState().setGlobalLevel(globalLevel);
  for (const [domain, level] of Object.entries(overrides) as [Domain, SkillLevel][]) {
    useSkillStore.getState().setRouteOverride(domain, level);
  }

  if (choices.tradingDefaults) {
    useSettingsStore.getState().setTradingDefaults({
      defaultExchange: choices.tradingDefaults.defaultExchange,
      defaultProduct: choices.tradingDefaults.defaultProduct,
      defaultQty: choices.tradingDefaults.defaultQty,
    });
  }

  if (choices.riskLimits) {
    useSettingsStore.getState().setRiskLimits(choices.riskLimits);
  }

  if (choices.llm) {
    const { provider, authMode } = providerSelection(choices.llm.provider);
    useSettingsStore.getState().setLLMSetupDraft({
      provider,
      authMode,
      model: choices.llm.model.trim(),
      host: normaliseLlmHost(provider, (choices.llm.host ?? "").trim()),
    });
  }

  const wizardPreset = getPresetName(experience, interests);
  const actualPresetId = mapWizardPreset(wizardPreset);
  const api = useLayoutStore.getState().workspaceApi;
  if (api) {
    useLayoutStore.getState().applyPreset(actualPresetId);
  } else {
    const activeTabId = useLayoutStore.getState().activeTabId;
    useLayoutStore.getState().saveTabLayout(activeTabId, {
      __pendingPreset: actualPresetId,
    } as unknown as Record<string, unknown>);
  }

  return personaRoute(persona);
}
