/**
 * Chat LLM readiness from GET /advisor/status.
 *
 * Badge and composer must follow this probe — not the persisted settings
 * store. Explore / demo-user sessions still run the request so a leftover
 * local provider cannot leave a stale Connected badge.
 */

import { useQuery } from "@tanstack/react-query";
import {
  isAdvisorChatReady,
  probeAdvisorAvailability,
  resolveAdvisorLlmChrome,
  type AdvisorLlmChrome,
} from "@/services/advisorChat";

export const ADVISOR_LLM_STATUS_QUERY_KEY = ["advisor-llm-readiness"] as const;

export interface AdvisorLlmStatus {
  chrome: AdvisorLlmChrome;
  configured: boolean;
  isLoading: boolean;
  refetch: () => Promise<unknown>;
}

export function useAdvisorLlmStatus(): AdvisorLlmStatus {
  const query = useQuery({
    queryKey: ADVISOR_LLM_STATUS_QUERY_KEY,
    queryFn: ({ signal }) => probeAdvisorAvailability(signal),
    staleTime: 0,
    refetchOnMount: "always",
    networkMode: "always",
    retry: false,
  });

  const chrome = resolveAdvisorLlmChrome({
    availability: query.data,
    isPending: query.isPending,
    isFetching: query.isFetching,
    fetchStatus: query.fetchStatus,
  });

  return {
    chrome,
    configured: isAdvisorChatReady(chrome),
    isLoading: chrome === "loading",
    refetch: query.refetch,
  };
}
