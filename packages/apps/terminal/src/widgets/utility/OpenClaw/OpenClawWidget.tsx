/**
 * OpenClawWidget — control plane for OpenClaw AI agent sessions.
 *
 * Reports the EXTERNAL OpenClaw gateway state via /api/v1/ai/openclaw/*.
 * All data is real: when the gateway is unreachable the status shows offline
 * and the list is empty; when the installed OpenClaw exposes no HTTP agent
 * lifecycle API, deploy/stop controls stay disabled instead of fabricating a
 * control plane.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, Play, Square, Wifi, WifiOff, ScrollText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  getOpenClawStatus,
  getOpenClawAgents,
  deployOpenClawAgent,
  stopOpenClawAgent,
  getOpenClawAgentLogs,
} from "@/services/ftApi.ai";

export default function OpenClawWidget() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [strategy, setStrategy] = useState("momentum");
  const [symbols, setSymbols] = useState("NIFTY");
  const [logsFor, setLogsFor] = useState<string | null>(null);

  const logsQuery = useQuery({
    queryKey: ["openclaw", "logs", logsFor],
    queryFn: () => getOpenClawAgentLogs(logsFor as string),
    enabled: logsFor !== null,
    refetchInterval: logsFor !== null ? 5_000 : false,
  });

  const statusQuery = useQuery({
    queryKey: ["openclaw", "status"],
    queryFn: getOpenClawStatus,
    refetchInterval: 30_000,
  });
  const agentsQuery = useQuery({
    queryKey: ["openclaw", "agents"],
    queryFn: getOpenClawAgents,
    refetchInterval: 15_000,
  });

  const connected = statusQuery.data?.connected ?? false;
  const agentControlSupported = statusQuery.data?.agent_control_supported ?? false;
  const statusMessage = statusQuery.data?.message ?? "";
  const agents = agentsQuery.data?.agents ?? [];

  const invalidateAgents = () =>
    queryClient.invalidateQueries({ queryKey: ["openclaw", "agents"] });

  const deploy = useMutation({
    mutationFn: () =>
      deployOpenClawAgent({
        name: name.trim(),
        strategy: strategy.trim(),
        symbols: symbols.split(",").map((s) => s.trim()).filter(Boolean),
      }),
    onSuccess: () => {
      setName("");
      invalidateAgents();
    },
  });

  const stop = useMutation({
    mutationFn: (agentId: string) => stopOpenClawAgent(agentId),
    onSuccess: invalidateAgents,
  });

  return (
    <div className="flex flex-col h-full p-3 gap-3" data-testid="openclaw-widget">
      {/* Header / connection status */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bot size={14} className="text-accent" aria-hidden="true" />
          <span className="text-sm font-semibold text-text-primary">OpenClaw Agents</span>
        </div>
        {connected && agentControlSupported ? (
          <span className="inline-flex items-center gap-1 text-xxs text-profit">
            <Wifi size={11} aria-hidden="true" /> Connected
          </span>
        ) : connected ? (
          <span className="inline-flex items-center gap-1 text-xxs text-warning">
            <Wifi size={11} aria-hidden="true" /> Gateway connected
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-xxs text-text-muted">
            <WifiOff size={11} aria-hidden="true" /> Gateway offline
          </span>
        )}
      </div>

      {/* Deploy form */}
      <form
        className="grid grid-cols-1 gap-2 rounded-lg border border-border-default bg-surface-base p-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) deploy.mutate();
        }}
      >
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Agent name"
          aria-label="Agent name"
          className="h-7 text-xs"
        />
        <div className="grid grid-cols-2 gap-2">
          <Input
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            placeholder="Strategy"
            aria-label="Strategy"
            className="h-7 text-xs"
          />
          <Input
            value={symbols}
            onChange={(e) => setSymbols(e.target.value)}
            placeholder="Symbols (comma-separated)"
            aria-label="Symbols"
            className="h-7 text-xs"
          />
        </div>
        <Button
          type="submit"
          size="sm"
          className="h-7 text-xs"
          disabled={!name.trim() || deploy.isPending || !connected || !agentControlSupported}
        >
          <Play size={12} className="mr-1" aria-hidden="true" />
          {deploy.isPending ? "Deploying…" : "Deploy agent"}
        </Button>
        {!connected ? (
          <p className="text-xxs text-text-muted">
            Connect the OpenClaw gateway to deploy agents.
          </p>
        ) : !agentControlSupported ? (
          <p className="text-xxs text-warning">
            {statusMessage || "OpenClaw HTTP agent lifecycle controls are unavailable."}
          </p>
        ) : null}
        {deploy.isError && (
          <p className="text-xxs text-loss">Deploy failed — OpenClaw rejected the request.</p>
        )}
      </form>

      {/* Agent list */}
      <div className="flex-1 overflow-y-auto space-y-1.5" aria-label="OpenClaw agents">
        {agents.length === 0 ? (
          <p className="text-xs text-text-muted py-4 text-center">
            {!connected
              ? "Gateway offline — no agents."
              : !agentControlSupported
                ? "Gateway connected — HTTP agent lifecycle unavailable."
                : "No agents running."}
          </p>
        ) : (
          agents.map((a) => (
            <div
              key={a.id}
              className="rounded border border-border-default bg-surface-base"
            >
              <div className="flex items-center justify-between gap-2 px-3 py-2">
                <div className="min-w-0">
                  <p className="text-xs font-medium text-text-primary truncate">
                    {a.name || a.id}
                  </p>
                  <p className="text-xxs text-text-muted truncate">
                    {a.strategy} · {a.status}
                  </p>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 px-2 text-xxs"
                    onClick={() => setLogsFor(logsFor === a.id ? null : a.id)}
                    aria-expanded={logsFor === a.id}
                    aria-label={`${logsFor === a.id ? "Hide" : "View"} logs for ${a.name || a.id}`}
                  >
                    <ScrollText size={10} className="mr-1" aria-hidden="true" /> Logs
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-6 px-2 text-xxs"
                    onClick={() => stop.mutate(a.id)}
                    disabled={stop.isPending}
                    aria-label={`Stop ${a.name || a.id}`}
                  >
                    <Square size={10} className="mr-1" aria-hidden="true" /> Stop
                  </Button>
                </div>
              </div>

              {logsFor === a.id && (
                <div className="border-t border-border-default px-3 py-2" data-testid="openclaw-logs">
                  {logsQuery.isLoading ? (
                    <p className="text-xxs text-text-muted">Loading logs…</p>
                  ) : (logsQuery.data?.logs?.length ?? 0) === 0 ? (
                    <p className="text-xxs text-text-muted">No logs available.</p>
                  ) : (
                    <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap text-xxs font-mono text-text-secondary">
                      {logsQuery.data?.logs?.join("\n")}
                    </pre>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
