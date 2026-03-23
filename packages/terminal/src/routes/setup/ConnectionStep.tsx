/**
 * ConnectionStep — OpenAlgo connection configuration step in the setup wizard.
 */

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { CheckCircle, XCircle, Loader2, Wifi, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useConnectionStore } from "@/stores/connectionStore";
import { ping } from "@/services/api";

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

export const connectionSchema = z.object({
  host: z.string().min(1, "Host is required").url("Must be a valid URL (include http://)"),
  apiKey: z.string().min(8, "API key must be at least 8 characters"),
  wsPort: z.string().min(1, "WebSocket port is required"),
});

export type ConnectionFormValues = z.infer<typeof connectionSchema>;

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

export function deriveWsUrl(host: string, wsPort: string): string {
  try {
    const url = new URL(host);
    const proto = url.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${url.hostname}:${wsPort}`;
  } catch {
    return `ws://localhost:${wsPort}`;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ConnectionStepProps {
  onComplete: (values: ConnectionFormValues) => void;
  defaultValues?: Partial<ConnectionFormValues>;
}

export function ConnectionStep({ onComplete, defaultValues }: ConnectionStepProps) {
  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors },
  } = useForm<ConnectionFormValues>({
    resolver: zodResolver(connectionSchema),
    defaultValues: {
      host: defaultValues?.host ?? "http://localhost:5000",
      apiKey: defaultValues?.apiKey ?? "",
      wsPort: defaultValues?.wsPort ?? "8765",
    },
  });

  const [testState, setTestState] = useState<"idle" | "testing" | "ok" | "fail">("idle");
  const [testError, setTestError] = useState("");

  async function handleTest() {
    const vals = getValues();
    const wsUrl = deriveWsUrl(vals.host, vals.wsPort);
    useConnectionStore.getState().setConfig({ host: vals.host, apiKey: vals.apiKey, wsUrl });

    setTestState("testing");
    setTestError("");
    try {
      await ping();
      setTestState("ok");
    } catch (err) {
      setTestState("fail");
      setTestError(err instanceof Error ? err.message : "Connection failed");
    }
  }

  return (
    <form onSubmit={handleSubmit(onComplete)} className="space-y-5">
      <div className="space-y-1.5">
        <Label htmlFor="host" className="text-text-secondary text-xs uppercase tracking-wider">
          OpenAlgo URL
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="host"
            placeholder="http://localhost:5000"
            aria-label="OpenAlgo URL"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("host")}
          />
        </div>
        {errors.host && (
          <p className="text-red-400 text-xs">{errors.host.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="apiKey" className="text-text-secondary text-xs uppercase tracking-wider">
          API Key
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="apiKey"
            type="password"
            placeholder="Your OpenAlgo API key"
            aria-label="OpenAlgo API key"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("apiKey")}
          />
        </div>
        {errors.apiKey && (
          <p className="text-red-400 text-xs">{errors.apiKey.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="wsPort" className="text-text-secondary text-xs uppercase tracking-wider">
          WebSocket Port
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="wsPort"
            placeholder="8765"
            aria-label="WebSocket port"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("wsPort")}
          />
        </div>
        {errors.wsPort && (
          <p className="text-red-400 text-xs">{errors.wsPort.message}</p>
        )}
      </div>

      <div className="flex items-center gap-3 pt-1">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void handleTest()}
          disabled={testState === "testing"}
          className="border-border-default text-text-secondary hover:text-text-primary"
        >
          {testState === "testing" ? (
            <Loader2 className="size-3.5 mr-1.5 animate-spin" />
          ) : (
            <Wifi className="size-3.5 mr-1.5" />
          )}
          Test Connection
        </Button>

        {testState === "ok" && (
          <span className="flex items-center gap-1.5 text-green-400 text-sm">
            <CheckCircle className="size-4" /> Connected
          </span>
        )}
        {testState === "fail" && (
          <span className="flex items-center gap-1.5 text-red-400 text-sm">
            <XCircle className="size-4" />
            <span className="truncate max-w-50">{testError || "Failed"}</span>
          </span>
        )}
      </div>

      <Button
        type="submit"
        className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
      >
        Continue
        <ArrowRight className="size-4 ml-2" />
      </Button>
    </form>
  );
}
