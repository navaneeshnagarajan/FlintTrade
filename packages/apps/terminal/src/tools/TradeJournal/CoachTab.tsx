import { useState, useMemo } from "react";
import { Brain, AlertCircle, Loader2 } from "lucide-react";
import { computeAnalytics } from "@/lib/journalAnalytics";
import { type JournalTrade } from "@/services/ftApi";
import { getBase, buildHeaders } from "@/services/ftApi.helpers";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { type TiltStatus } from "./types";
import { detectTilt } from "./utils";

function TiltBadge({ status }: { status: TiltStatus }) {
  if (status.level === "tilted") {
    return (
      <Badge className="bg-red-900/40 text-red-400 border-red-700/40 text-xs font-semibold">
        Tilt Detected
      </Badge>
    );
  }
  if (status.level === "warning") {
    return (
      <Badge className="bg-yellow-900/40 text-yellow-400 border-yellow-700/40 text-xs font-semibold">
        Caution
      </Badge>
    );
  }
  return (
    <Badge className="bg-emerald-900/40 text-emerald-400 border-emerald-700/40 text-xs font-semibold">
      Focused
    </Badge>
  );
}

export function CoachTab({ trades }: { trades: JournalTrade[] }) {
  const [aiResponse, setAiResponse] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  const a = useMemo(() => computeAnalytics(trades), [trades]);
  const tilt = useMemo(() => detectTilt(trades), [trades]);

  const winRate = a.winRate.toFixed(1);
  const avgWin = a.avgWin.toFixed(0);
  const avgLoss = Math.abs(a.avgLoss).toFixed(0);
  const streak =
    a.streakType === "none"
      ? "No streak"
      : `${a.currentStreak} ${a.streakType === "win" ? "win" : "loss"} streak`;

  async function handleAiCoach() {
    setIsLoading(true);
    setAiError(null);
    setAiResponse(null);

    try {
      const base = getBase();
      const res = await fetch(`${base}/api/v1/advisor`, {
        method: "POST",
        // buildHeaders, not a bare Content-Type. This was the only advisor
        // caller sending no X-API-Key and no session JWT, so it depended on
        // the route being unauthenticated — which is not something a caller
        // should assume, and not something that stays true.
        headers: buildHeaders(true),
        body: JSON.stringify({
          message: `Analyse my recent trading behaviour. Win rate: ${winRate}%, Average win: ₹${avgWin}, Average loss: ₹${avgLoss}, Current streak: ${streak}. What patterns do you see and what should I improve?`,
        }),
      });

      if (!res.ok) {
        const err = (await res.json().catch(() => ({}))) as { message?: string };
        setAiError(err.message ?? `Request failed (${res.status})`);
        return;
      }

      const data = (await res.json()) as { data?: { response?: string }; response?: string };
      const reply = data?.data?.response ?? data?.response ?? "";
      setAiResponse(reply || "No response from advisor.");
    } catch (err) {
      setAiError(err instanceof Error ? err.message : "Network error");
    } finally {
      setIsLoading(false);
    }
  }

  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-text-muted">
        <Brain size={40} />
        <p className="text-sm">No trade data for coaching</p>
      </div>
    );
  }

  return (
    <ScrollArea className="flex-1 px-3 py-2">
      <div className="space-y-3">
        {/* Tilt detection */}
        <Card className="bg-surface-card border-border-default">
          <CardHeader className="p-3 pb-1">
            <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
              Behavioural State
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-2 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-muted">Current state:</span>
              <TiltBadge status={tilt} />
            </div>
            {tilt.reason && (
              <p
                className={`text-xs ${tilt.level === "tilted" ? "text-red-400" : "text-yellow-400"}`}
                role="alert"
              >
                {tilt.reason}
              </p>
            )}
          </CardContent>
        </Card>

        {/* Behavioural summary */}
        <Card className="bg-surface-card border-border-default">
          <CardHeader className="p-3 pb-1">
            <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
              Pattern Summary
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-1">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
              <div className="flex justify-between items-center">
                <span className="text-xs text-text-muted">Win rate</span>
                <span
                  className={`text-xs font-mono font-semibold ${a.winRate >= 50 ? "text-profit" : "text-loss"}`}
                >
                  {winRate}%
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-text-muted">Streak</span>
                <span
                  className={`text-xs font-mono font-semibold ${
                    a.streakType === "win"
                      ? "text-profit"
                      : a.streakType === "loss"
                        ? "text-loss"
                        : "text-text-muted"
                  }`}
                >
                  {streak}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-text-muted">Avg win</span>
                <span className="text-xs font-mono text-profit">₹{avgWin}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-text-muted">Avg loss</span>
                <span className="text-xs font-mono text-loss">₹{avgLoss}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-text-muted">Profit factor</span>
                <span
                  className={`text-xs font-mono font-semibold ${a.profitFactor >= 1 ? "text-profit" : "text-loss"}`}
                >
                  {isFinite(a.profitFactor) ? a.profitFactor.toFixed(2) : "∞"}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-text-muted">Total trades</span>
                <span className="text-xs font-mono text-text-primary">{a.totalTrades}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* AI Coaching */}
        <Card className="bg-surface-card border-border-default">
          <CardHeader className="p-3 pb-1">
            <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
              AI Coaching
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-2 space-y-2">
            <Button
              size="sm"
              className="w-full h-8 text-xs gap-1.5"
              onClick={handleAiCoach}
              disabled={isLoading}
              aria-busy={isLoading}
            >
              {isLoading ? (
                <Loader2 size={12} className="animate-spin" aria-hidden="true" />
              ) : (
                <Brain size={12} aria-hidden="true" />
              )}
              {isLoading ? "Analyzing..." : "Request AI Coaching Analysis"}
            </Button>

            {aiError && (
              <div
                className="flex items-start gap-1.5 text-xs text-loss bg-red-900/10 border border-red-900/20 rounded p-2"
                role="alert"
              >
                <AlertCircle size={12} className="shrink-0 mt-0.5" />
                <span>{aiError}</span>
              </div>
            )}

            {aiResponse && (
              <div
                className="text-xs text-text-secondary leading-relaxed bg-surface-base rounded p-2.5 whitespace-pre-wrap"
                aria-live="polite"
              >
                {aiResponse}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </ScrollArea>
  );
}
