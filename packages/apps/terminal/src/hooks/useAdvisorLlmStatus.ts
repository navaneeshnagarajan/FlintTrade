/**
 * Chat LLM readiness from advisor/status, aligned with Settings `#llm`.
 *
 * Explore / demo-user still probe advisor/status, but a Settings empty
 * appearance (FT-SET-001) wins over an env-default ``configured: true``.
 */

import { useQuery } from "@tanstack/react-query";
import {
  alignAdvisorChromeWithSettingsHydration,
  isAdvisorChatReady,
  probeAdvisorAvailability,
  resolveAdvisorLlmChrome,
  type AdvisorLlmChrome,
} from "@/services/advisorChat";
import { probeSettingsLlmHydration } from "@/hooks/useSettingsState";

export const ADVISOR_LLM_STATUS_QUERY_KEY = ["advisor-llm-readiness"] as const;
export const SETTINGS_LLM_HYDRATION_QUERY_KEY = ["settings-llm-hydration"] as const;

export interface AdvisorLlmStatus {
  chrome: AdvisorLlmChrome;
  configured: boolean;
  isLoading: boolean;
  refetch: () => Promise<unknown>;
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
    queryFn: probeSettingsLlmHydration,
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
  const settingsHydration =
    settingsQuery.isPending || settingsQuery.isFetching
      ? "loading"
      : (settingsQuery.data ?? "loading");
  const chrome = alignAdvisorChromeWithSettingsHydration(advisorChrome, settingsHydration);

  return {
    chrome,
    configured: isAdvisorChatReady(chrome),
    isLoading: chrome === "loading",
    refetch: async () => {
      await Promise.all([advisorQuery.refetch(), settingsQuery.refetch()]);
    },
  };
}
