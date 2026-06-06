/**
 * OpenClawWidget — control plane for OpenClaw autonomous trading agents.
 *
 * Lists agents running on the EXTERNAL OpenClaw gateway, deploys new ones, and
 * stops running ones, via /api/v1/ai/openclaw/*. All data is real: when the
 * gateway is unreachable the status shows offline and the list is empty — there
 * are no fabricated agents. The agents trade through OpenClaw's own broker
 * connection, so nothing here touches FlintTrade's gated order path.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, Play, Square, Wifi, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  getOpenClawStatus,
  getOpenClawAgents,
  deployOpenClawAgent,
  stopOpenClawAgent,
} from "@/services/ftApi.ai";

export default function OpenClawWidget() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [strategy, setStrategy] = useState("momentum");
  const [symbols, setSymbols] = useState("NIFTY");

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
        {connected ? (
          <span className="inline-flex items-center gap-1 text-xxs text-profit">
            <Wifi size={11} aria-hidden="true" /> Connected
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
          disabled={!name.trim() || deploy.isPending || !connected}
        >
          <Play size={12} className="mr-1" aria-hidden="true" />
          {deploy.isPending ? "Deploying…" : "Deploy agent"}
        </Button>
        {!connected && (
          <p className="text-xxs text-text-muted">
            Connect the OpenClaw gateway to deploy agents.
          </p>
        )}
        {deploy.isError && (
          <p className="text-xxs text-loss">Deploy failed — is OpenClaw reachable?</p>
        )}
      </form>

      {/* Agent list */}
      <div className="flex-1 overflow-y-auto space-y-1.5" aria-label="OpenClaw agents">
        {agents.length === 0 ? (
          <p className="text-xs text-text-muted py-4 text-center">
            {connected ? "No agents running." : "Gateway offline — no agents."}
          </p>
        ) : (
          agents.map((a) => (
            <div
              key={a.id}
              className="flex items-center justify-between gap-2 rounded border border-border-default bg-surface-base px-3 py-2"
            >
              <div className="min-w-0">
                <p className="text-xs font-medium text-text-primary truncate">
                  {a.name || a.id}
                </p>
                <p className="text-xxs text-text-muted truncate">
                  {a.strategy} · {a.status}
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                className="h-6 px-2 text-xxs shrink-0"
                onClick={() => stop.mutate(a.id)}
                disabled={stop.isPending}
                aria-label={`Stop ${a.name || a.id}`}
              >
                <Square size={10} className="mr-1" aria-hidden="true" /> Stop
              </Button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
