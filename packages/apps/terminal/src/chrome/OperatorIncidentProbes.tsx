/**
 * Desk probes that fill the operator-incident store. Mount once, outside tests.
 */

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAdvisorLlmStatus } from "@/hooks/useAdvisorLlmStatus";
import { LAYA_STATUS_POLL_MS } from "@/lib/layaStatus";
import {
  probeDeskHealth,
  probeLocalPing,
  probePublicInternet,
  probePublicSite,
  type PingProbe,
} from "@/lib/operatorProbes";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";

interface LayaPingSample {
  probe: PingProbe;
  epoch: number;
}

export function OperatorIncidentProbes() {
  const ping = useQuery({
    queryKey: ["operator", "ping"],
    queryFn: async (): Promise<LayaPingSample> => {
      const epoch = useOperatorSignalStore.getState().layaEpoch;
      return { probe: await probeLocalPing(), epoch };
    },
    refetchInterval: LAYA_STATUS_POLL_MS,
    refetchIntervalInBackground: true,
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
  const internet = useQuery({
    queryKey: ["operator", "internet"],
    queryFn: () => probePublicInternet(),
    refetchInterval: 300_000,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 60_000,
  });
  const llm = useAdvisorLlmStatus();

  useEffect(() => {
    if (!ping.data) return;
    const store = useOperatorSignalStore.getState();
    if (ping.data.epoch !== store.layaEpoch) return;
    const sample = ping.data.probe;
    store.setLayaChecking(false);
    store.setPing(sample);
    store.setDecisionStatus(sample.laya ?? "down");
    store.setLayaPracticeStatus(sample.layaPractice ?? "down");
    store.setLayaLiveQualified(sample.layaLiveQualified);
    store.setLayaReason(sample.layaReason);
    store.setLayaPort(sample.layaPort);
    store.setLayaDownloadProgress(sample.layaDownloadBytes, sample.layaDownloadTotal);
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
    if (!internet.data) return;
    useOperatorSignalStore.getState().setPublicInternet(internet.data);
  }, [internet.data]);

  useEffect(() => {
    useOperatorSignalStore.getState().setLlmChrome(llm.chrome);
  }, [llm.chrome]);

  return null;
}
