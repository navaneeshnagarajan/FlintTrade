import { useEffect, useRef, useState } from "react";
import wsService from "../services/websocket";

/**
 * React hook wrapping the WebSocket service.
 * Subscribe to instruments on mount, unsubscribe on unmount.
 * Returns the latest tick keyed by "exchange:symbol".
 *
 * @param {Array<{symbol:string,exchange:string}>} instruments
 * @param {string} mode - "ltp" | "quote" | "depth"
 */
export default function useWebSocket(instruments = [], mode = "ltp") {
  const [ticks, setTicks] = useState({});
  const [connected, setConnected] = useState(wsService.connected);
  const prevRef = useRef([]);

  useEffect(() => {
    if (!wsService.connected) wsService.connect();

    const onTick = (e) => {
      const d = e.detail;
      if (d?.symbol && d?.exchange) {
        const key = `${d.exchange}:${d.symbol}`;
        setTicks((prev) => ({ ...prev, [key]: d }));
      }
    };

    const onStatus = (e) => setConnected(e.detail?.connected ?? false);

    window.addEventListener("ws:tick", onTick);
    window.addEventListener("ws:status", onStatus);
    return () => {
      window.removeEventListener("ws:tick", onTick);
      window.removeEventListener("ws:status", onStatus);
    };
  }, []);

  useEffect(() => {
    if (instruments.length === 0) return;
    const toAdd = instruments.filter(
      (i) => !prevRef.current.some((p) => p.symbol === i.symbol && p.exchange === i.exchange)
    );
    const toRemove = prevRef.current.filter(
      (p) => !instruments.some((i) => i.symbol === p.symbol && i.exchange === p.exchange)
    );
    if (toRemove.length) wsService.unsubscribe(toRemove, mode);
    if (toAdd.length) wsService.subscribe(toAdd, mode);
    prevRef.current = instruments;

    return () => {
      if (prevRef.current.length) wsService.unsubscribe(prevRef.current, mode);
      prevRef.current = [];
    };
  }, [JSON.stringify(instruments), mode]);

  return { ticks, connected };
}
