/**
 * Chat LLM readiness from GET /advisor/status.
 *
 * Badge and composer must follow this probe — not the persisted settings
 * store. Explore / demo-user sessions still run the request so a leftover
 * local provider cannot leave a stale Connected badge.
 */

import { useQuery } from "@tanstack/react-query";
import {
  advisorAvailabilityToChrome,
  isAdvisorChatReady,
  probeAdvisorAvailability,
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
    staleTime: 30_000,
    retry: false,
  });

  const chrome = advisorAvailabilityToChrome(query.isPending ? undefined : query.data);

  return {
    chrome,
    configured: isAdvisorChatReady(chrome),
    isLoading: query.isPending,
    refetch: query.refetch,
  };
}
