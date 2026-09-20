/**
 * Chat LLM readiness from advisor/status, aligned with Settings `#llm`.
 *
 * Explore / demo-user still probe advisor/status, but a Settings empty
 * appearance (FT-SET-001) wins over an env-default ``configured: true``.
 * Managed Ollama ``Not installed`` never paints Connected (FT-AI-004).
 */

import { useQuery } from "@tanstack/react-query";
import {
  alignAdvisorChromeWithManagedOllama,
  alignAdvisorChromeWithSettingsHydration,
  isAdvisorChatReady,
  probeAdvisorAvailability,
  selectsManagedOllama,
  type AdvisorLlmChrome,
  type ManagedOllamaInstall,
  resolveAdvisorLlmChrome,
} from "@/services/advisorChat";
import { probeSettingsLlmReadiness } from "@/hooks/useSettingsState";
import { getLocalAiStatus } from "@/services/ftApi.localAi";

export const ADVISOR_LLM_STATUS_QUERY_KEY = ["advisor-llm-readiness"] as const;
export const SETTINGS_LLM_HYDRATION_QUERY_KEY = ["settings-llm-hydration"] as const;
export const MANAGED_OLLAMA_INSTALL_QUERY_KEY = ["managed-ollama-install"] as const;

export interface AdvisorLlmStatus {
  chrome: AdvisorLlmChrome;
  configured: boolean;
  isLoading: boolean;
  refetch: () => Promise<unknown>;
}

export async function probeManagedOllamaInstall(): Promise<ManagedOllamaInstall> {
  try {
    const status = await getLocalAiStatus();
    return status.installed ? "installed" : "not_installed";
  } catch {
    return "unknown";
  }
}

export function useAdvisorLlmStatus(): AdvisorLlmStatus {
  const advisorQuery = useQuery({
    queryKey: ADVISOR_LLM_STATUS_QUERY_KEY,
    queryFn: ({ signal }) => probeAdvisorAvailability(signal),
    staleTime: 0,
    refetchOnMount: "always",
    networkMode: "always",
    retry: false,
  });
  const settingsQuery = useQuery({
    queryKey: SETTINGS_LLM_HYDRATION_QUERY_KEY,
    queryFn: probeSettingsLlmReadiness,
    staleTime: 0,
    refetchOnMount: "always",
    networkMode: "always",
    retry: false,
  });
  const settingsHydration =
    settingsQuery.isPending || settingsQuery.isFetching
      ? "loading"
      : (settingsQuery.data?.hydration ?? "loading");
  const settingsProvider = settingsQuery.data?.provider ?? "";
  const needsInstallProbe =
    settingsHydration === "ready" && selectsManagedOllama(settingsProvider);

  const installQuery = useQuery({
    queryKey: MANAGED_OLLAMA_INSTALL_QUERY_KEY,
    queryFn: probeManagedOllamaInstall,
    enabled: needsInstallProbe,
    staleTime: 0,
    refetchOnMount: "always",
    networkMode: "always",
    retry: false,
  });

  const advisorChrome = resolveAdvisorLlmChrome({
    availability: advisorQuery.data,
    isPending: advisorQuery.isPending,
    isFetching: advisorQuery.isFetching,
    fetchStatus: advisorQuery.fetchStatus,
  });
  const install: ManagedOllamaInstall = needsInstallProbe
    ? (installQuery.isPending || installQuery.isFetching
      ? "loading"
      : (installQuery.data ?? "loading"))
    : "not_applicable";
  const chrome = alignAdvisorChromeWithManagedOllama(
    alignAdvisorChromeWithSettingsHydration(advisorChrome, settingsHydration),
    install,
  );

  return {
    chrome,
    configured: isAdvisorChatReady(chrome),
    isLoading: chrome === "loading",
    refetch: async () => {
      await Promise.all([
        advisorQuery.refetch(),
        settingsQuery.refetch(),
        needsInstallProbe ? installQuery.refetch() : Promise.resolve(),
      ]);
    },
  };
}
