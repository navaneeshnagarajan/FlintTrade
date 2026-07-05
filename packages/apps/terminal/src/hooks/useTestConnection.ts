/**
 * useTestConnection — shared hook for testing OpenAlgo connectivity.
 * Used by ConnectionSection (Settings) and ConnectionStep (setup wizard).
 */

import { useState, useCallback } from "react";
import { testOpenAlgoConnection } from "@/services/ftApi.openalgo";

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
      const data = await testOpenAlgoConnection({ host, apiKey });

      if (data.status === "ok") {
        setStatus("ok");
        setMessage(data.message || "Connected successfully");
      } else {
        setStatus("error");
        setMessage(data.message || (data.httpStatus ? `Server returned ${data.httpStatus}` : "Connection test failed"));
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
