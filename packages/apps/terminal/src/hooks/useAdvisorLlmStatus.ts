/**
 * Chat LLM readiness from stored Settings `#llm` + advisor/status + install.
 *
 * Readiness is global config truth, not Mode-derived. Explore and Practice
 * share this hook. A blank stored provider is Not configured unless
 * ``advisor/status`` reports an explicit env-backed or stored provider
 * (``LLM_PROVIDER``). The empty→ollama default never paints Connected.
 * Managed Ollama ``Not installed`` never paints Connected (FT-AI-004).
 */

import { useQuery } from "@tanstack/react-query";
import {
  alignAdvisorChromeWithManagedOllama,
  alignAdvisorChromeWithSettingsHydration,
  isAdvisorChatReady,
  isExplicitAdvisorConfiguration,
  probeAdvisorStatus,
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
    queryFn: ({ signal }) => probeAdvisorStatus(signal),
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
  const advisorHint = {
    availability: advisorQuery.data?.availability,
    provider: advisorQuery.data?.provider ?? "",
    source: advisorQuery.data?.source ?? "",
  };
  const envOrStoredOllama = isExplicitAdvisorConfiguration(advisorHint)
    && selectsManagedOllama(advisorHint.provider);
  const needsInstallProbe =
    (settingsHydration === "ready" && selectsManagedOllama(settingsProvider))
    || envOrStoredOllama;

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
    availability: advisorQuery.data?.availability,
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
    alignAdvisorChromeWithSettingsHydration(
      advisorChrome,
      settingsHydration,
      settingsProvider,
      advisorHint,
    ),
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
