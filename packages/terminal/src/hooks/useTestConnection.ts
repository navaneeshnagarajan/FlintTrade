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
      const response = await fetch(`${host.replace(/\/$/, "")}/api/v1/ping`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ apikey: apiKey }),
        signal: AbortSignal.timeout(5000),
      });
      if (response.ok) {
        setStatus("ok");
        setMessage("Connected successfully");
      } else {
        setStatus("error");
        setMessage(`Server returned ${response.status}`);
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
