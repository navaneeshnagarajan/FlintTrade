/**
 * Desk probes that fill the operator-incident store. Mount once, outside tests.
 */

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAdvisorLlmStatus } from "@/hooks/useAdvisorLlmStatus";
import { probeDeskHealth, probeLocalPing, probePublicSite } from "@/lib/operatorProbes";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";

export function OperatorIncidentProbes() {
  const ping = useQuery({
    queryKey: ["operator", "ping"],
    queryFn: () => probeLocalPing(),
    refetchInterval: 30_000,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const health = useQuery({
    queryKey: ["operator", "health"],
    queryFn: () => probeDeskHealth(),
    refetchInterval: 30_000,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const edge = useQuery({
    queryKey: ["operator", "edge"],
    queryFn: () => probePublicSite(),
    refetchInterval: 300_000,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 60_000,
  });
  const llm = useAdvisorLlmStatus();

  useEffect(() => {
    if (!ping.data) return;
    useOperatorSignalStore.getState().setPing(ping.data);
  }, [ping.data]);

  useEffect(() => {
    if (!health.data) return;
    useOperatorSignalStore.getState().setHealth(health.data);
  }, [health.data]);

  useEffect(() => {
    if (!edge.data) return;
    useOperatorSignalStore.getState().setPublicSite(edge.data);
  }, [edge.data]);

  useEffect(() => {
    useOperatorSignalStore.getState().setLlmChrome(llm.chrome);
  }, [llm.chrome]);

  return null;
}
