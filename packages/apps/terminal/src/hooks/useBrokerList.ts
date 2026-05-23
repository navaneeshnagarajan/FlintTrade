import { useQuery } from "@tanstack/react-query";
import { gatewayApi } from "@/services/gatewayApi";

export function useBrokerList() {
  return useQuery({
    queryKey: ["gateway", "brokers"],
    queryFn: gatewayApi.listBrokers,
    staleTime: 60_000 * 60, // broker list rarely changes
  });
}
