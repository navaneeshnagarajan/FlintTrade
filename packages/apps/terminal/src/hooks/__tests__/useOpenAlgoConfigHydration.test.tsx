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

  it("hydrates non-secret connection cache fields from backend config", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({
        status: "success",
        data: {
          api_key_configured: true,
          api_key_last4: "-key",
          host: "http://192.168.1.20",
          port: 5001,
          ws_port: 8770,
        },
      }),
    } as Response)));

    renderHook(() => useOpenAlgoConfigHydration());

    await waitFor(() => {
      expect(useConnectionStore.getState().host).toBe("http://192.168.1.20");
      expect(useConnectionStore.getState().wsUrl).toBe("ws://192.168.1.20:8770");
    });
    expect(useConnectionStore.getState().apiKey).toBe("");
  });

  it("preserves an in-memory API key entered during the current session", () => {
    useConnectionStore.getState().setConfig({ apiKey: "typed-this-session" });

    applyOpenAlgoConfigToConnectionCache({
      host: "http://127.0.0.1",
      ws_port: 8765,
    });

    expect(useConnectionStore.getState().apiKey).toBe("typed-this-session");
  });
});
