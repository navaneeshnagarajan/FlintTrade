/**
 * useTestConnection — shared hook for testing OpenAlgo connectivity.
 * Used by ConnectionSection (Settings) and ConnectionStep (setup wizard).
 */

import { useState, useCallback } from "react";

export type TestConnectionStatus = "idle" | "testing" | "ok" | "error";

export interface UseTestConnectionResult {
  status: TestConnectionStatus;
  message: string;
  testConnection: (host: string, apiKey: string) => Promise<void>;
  reset: () => void;
}

export function useTestConnection(): UseTestConnectionResult {
  const [status, setStatus] = useState<TestConnectionStatus>("idle");
  const [message, setMessage] = useState("");

  const testConnection = useCallback(async (host: string, apiKey: string) => {
    setStatus("testing");
    setMessage("");
    try {
      // Route the test through our backend (same-origin) — browser → OpenAlgo
      // direct is blocked by CORS because OpenAlgo does not send
      // Access-Control-Allow-Origin for our origin. The backend pings
      // server-to-server and returns a structured result.
      const response = await fetch("/ft-api/v1/test-connection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          host: host.replace(/\/+$/, ""),   // strip one or more trailing slashes
          api_key: apiKey,
        }),
        signal: AbortSignal.timeout(10_000),
      });
      const data: { status?: string; message?: string } = await response
        .json()
        .catch(() => ({ status: "error", message: "Invalid JSON from backend" }));

      if (response.ok && data.status === "ok") {
        setStatus("ok");
        setMessage(data.message || "Connected successfully");
      } else {
        setStatus("error");
        setMessage(data.message || `Server returned ${response.status}`);
      }
    } catch (err) {
      setStatus("error");
      setMessage(err instanceof Error ? err.message : "Connection failed");
    }
  }, []);

  const reset = useCallback(() => {
    setStatus("idle");
    setMessage("");
  }, []);

  return { status, message, testConnection, reset };
}
