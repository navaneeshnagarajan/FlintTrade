import { useEffect, useRef, useState } from "react";
import { resolveMarketDataScope } from "@/lib/marketDataScope";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";

function currentScope(): string {
  const { accounts, activeAccountId } = useBrokerStore.getState();
  return resolveMarketDataScope({ mode: useModeStore.getState().mode, accounts, activeAccountId });
}

/** Retire local observations even when React batches an A → B → A transition. */
export function useMarketObservationEpoch() {
  const [epoch, setEpoch] = useState(0);
  const currentEpoch = useRef(0);
  useEffect(() => {
    let scope = currentScope();
    const changed = () => {
      const next = currentScope();
      if (next === scope) return;
      scope = next;
      currentEpoch.current += 1;
      setEpoch(currentEpoch.current);
    };
    const releaseMode = useModeStore.subscribe(changed);
    const releaseBroker = useBrokerStore.subscribe(changed);
    return () => { releaseMode(); releaseBroker(); };
  }, []);
  return { epoch, currentEpoch };
}
