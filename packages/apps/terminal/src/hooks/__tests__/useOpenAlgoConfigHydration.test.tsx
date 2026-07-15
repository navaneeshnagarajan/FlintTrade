import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import {
  applyOpenAlgoConfigToConnectionCache,
  deriveOpenAlgoWsUrl,
  openAlgoRestPortFromHost,
  openAlgoWsPortFromUrl,
  useOpenAlgoConfigHydration,
} from "../useOpenAlgoConfigHydration";
import { useConnectionStore } from "@/stores/connectionStore";

describe("useOpenAlgoConfigHydration", () => {
  beforeEach(() => {
    useConnectionStore.setState(useConnectionStore.getInitialState());
    vi.unstubAllGlobals();
  });

  it("derives websocket and port values from OpenAlgo URLs", () => {
    expect(deriveOpenAlgoWsUrl("https://openalgo.local:5000", "8770")).toBe("wss://openalgo.local:8770");
    expect(openAlgoRestPortFromHost("http://127.0.0.1:5001")).toBe("5001");
    expect(openAlgoWsPortFromUrl("ws://127.0.0.1:8765")).toBe("8765");
  });

  it("rehydrates the raw bridge apiKey and opens the routing gate from backend config", async () => {
    // The store is memory-only, so the raw key is re-fetched over loopback on
    // every load. Until this completes openAlgoHydrated is false so live-order
    // routing fails closed; after it, the apiKey is restored without a re-type.
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({
        status: "success",
        data: {
          api_key: "live-bridge-key",
          api_key_configured: true,
          api_key_last4: "-key",
          host: "http://192.168.1.20",
          port: 5001,
          ws_port: 8770,
        },
      }),
    } as Response)));

    expect(useConnectionStore.getState().openAlgoHydrated).toBe(false);

    renderHook(() => useOpenAlgoConfigHydration());

    await waitFor(() => {
      expect(useConnectionStore.getState().openAlgoHydrated).toBe(true);
    });
    expect(useConnectionStore.getState().host).toBe("http://192.168.1.20");
    expect(useConnectionStore.getState().wsUrl).toBe("ws://192.168.1.20:8770");
    expect(useConnectionStore.getState().apiKey).toBe("live-bridge-key");
  });

  it("leaves the routing gate closed while the config read has not yet completed", () => {
    // A never-resolving fetch models the async hydration window. The gate must
    // remain closed so a live order attempted in this window fails closed.
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    renderHook(() => useOpenAlgoConfigHydration());

    expect(useConnectionStore.getState().openAlgoHydrated).toBe(false);
  });

  it("does not read protected config and clears runtime credentials without an authenticated owner", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    useConnectionStore.setState({
      apiKey: "session-only-key",
      host: "http://127.0.0.1:5000",
      wsUrl: "ws://127.0.0.1:8765",
      openAlgoHydrated: true,
    });

    renderHook(() => useOpenAlgoConfigHydration(false));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(useConnectionStore.getState()).toMatchObject({
      apiKey: "",
      host: "",
      wsUrl: "",
      openAlgoHydrated: false,
    });
  });

  it("preserves an in-memory API key when the backend omits api_key", () => {
    useConnectionStore.getState().setConfig({ apiKey: "typed-this-session" });

    applyOpenAlgoConfigToConnectionCache({
      host: "http://127.0.0.1",
      ws_port: 8765,
    });

    expect(useConnectionStore.getState().apiKey).toBe("typed-this-session");
  });

  it("applies an explicitly empty api_key (bridge cleared) over a stale in-memory key", () => {
    useConnectionStore.getState().setConfig({ apiKey: "stale-key" });

    applyOpenAlgoConfigToConnectionCache({
      api_key: "",
      host: "http://127.0.0.1",
      ws_port: 8765,
    });

    expect(useConnectionStore.getState().apiKey).toBe("");
  });
});
