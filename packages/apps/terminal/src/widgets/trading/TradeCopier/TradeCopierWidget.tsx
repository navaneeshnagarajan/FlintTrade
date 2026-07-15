/**
 * Compact operational surface for the gated Ditto multi-account runtime.
 * Account credentials and risk configuration remain owned by the full /ditto route.
 */

import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Check,
  Copy,
  ExternalLink,
  Play,
  RefreshCw,
  Square,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  getDittoAccounts,
  getDittoMirrorStatus,
  getDittoRisk,
  type MirrorMode,
  type MirrorStatus,
  setDittoAccountEnabled,
  startDittoMirror,
  stopDittoMirror,
} from "@/services/ftApi";

const EMPTY_STATUS: MirrorStatus = {
  active: false,
  source_account: null,
  target_accounts: [],
  mode: "weighted",
  mirrored_positions: 0,
  last_sync: null,
  errors: [],
};

const MODE_LABELS: Record<MirrorMode, string> = {
  equal: "Copy 1:1",
  weighted: "By weight",
};

const MODE_DESCRIPTIONS: Record<MirrorMode, string> = {
  equal: "Copy the full source quantity to every target account",
  weighted: "Split the source quantity using each target's allocation weight",
};

function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

function mutationError(error: unknown): string {
  return error instanceof Error ? error.message : "Ditto operation failed";
}

function TradeCopierWidget() {
  const queryClient = useQueryClient();
  const accountsQuery = useQuery({
    queryKey: ["ditto", "accounts"],
    queryFn: getDittoAccounts,
    refetchInterval: 30_000,
    retry: 1,
  });
  const statusQuery = useQuery({
    queryKey: ["ditto", "mirror", "status"],
    queryFn: getDittoMirrorStatus,
    refetchInterval: 10_000,
    retry: 1,
  });
  const riskQuery = useQuery({
    queryKey: ["ditto", "risk"],
    queryFn: getDittoRisk,
    refetchInterval: 15_000,
    retry: 1,
  });

  const [sourceAccount, setSourceAccount] = useState("");
  const [targetAccounts, setTargetAccounts] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<MirrorMode>("weighted");

  const accounts = useMemo(() => accountsQuery.data?.accounts ?? [], [accountsQuery.data]);
  const activeAccounts = useMemo(
    () => accounts.filter((account) => account.status === "active"),
    [accounts],
  );
  const status = statusQuery.data ?? EMPTY_STATUS;

  useEffect(() => {
    if (!status.active) return;
    setSourceAccount(status.source_account ?? "");
    setTargetAccounts(new Set(status.target_accounts));
    setMode(status.mode);
  }, [status.active, status.mode, status.source_account, status.target_accounts]);

  useEffect(() => {
    if (status.active || activeAccounts.length === 0) return;
    const sourceIsUsable = activeAccounts.some((account) => account.id === sourceAccount);
    if (!sourceIsUsable) {
      const preferred = activeAccounts.find((account) => account.is_master) ?? activeAccounts[0];
      setSourceAccount(preferred.id);
    }
  }, [activeAccounts, sourceAccount, status.active]);

  useEffect(() => {
    if (status.active) return;
    const activeIds = new Set(activeAccounts.map((account) => account.id));
    setTargetAccounts((current) => {
      const valid = new Set([...current].filter((id) => id !== sourceAccount && activeIds.has(id)));
      if (valid.size === current.size && [...valid].every((id) => current.has(id))) return current;
      return valid;
    });
  }, [activeAccounts, sourceAccount, status.active]);

  const refreshDitto = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["ditto"] });
  }, [queryClient]);

  const startMutation = useMutation({
    mutationFn: () => startDittoMirror(sourceAccount, [...targetAccounts], mode),
    onSuccess: refreshDitto,
  });
  const stopMutation = useMutation({
    mutationFn: stopDittoMirror,
    onSuccess: refreshDitto,
  });
  const accountMutation = useMutation({
    mutationFn: ({ accountId, enabled }: { accountId: string; enabled: boolean }) =>
      setDittoAccountEnabled(accountId, enabled),
    onSuccess: (_account, variables) => {
      if (!variables.enabled) {
        setTargetAccounts((current) => {
          const next = new Set(current);
          next.delete(variables.accountId);
          return next;
        });
      }
      refreshDitto();
    },
  });

  const setSource = useCallback((accountId: string) => {
    setSourceAccount(accountId);
    setTargetAccounts((current) => {
      const next = new Set(current);
      next.delete(accountId);
      return next;
    });
  }, []);

  const toggleTarget = useCallback((accountId: string) => {
    setTargetAccounts((current) => {
      const next = new Set(current);
      if (next.has(accountId)) next.delete(accountId);
      else next.add(accountId);
      return next;
    });
  }, []);

  const actionError = startMutation.isError
    ? mutationError(startMutation.error)
    : stopMutation.isError
      ? mutationError(stopMutation.error)
      : accountMutation.isError
        ? mutationError(accountMutation.error)
        : "";
  const isMutating = startMutation.isPending || stopMutation.isPending || accountMutation.isPending;
  const canStart = Boolean(
    !status.active
    && !statusQuery.isError
    && sourceAccount
    && targetAccounts.size > 0
    && !isMutating,
  );

  return (
    <div className="flex h-full flex-col overflow-hidden bg-surface-base" data-testid="tradecopier-widget">
      <div className="flex flex-none items-center gap-2 border-b border-border-default bg-surface-card px-3 py-2">
        <Copy size={13} className="flex-none text-accent" aria-hidden="true" />
        <span className="text-sm font-medium text-text-primary">Trade Copier</span>
        <Badge
          variant="outline"
          className={statusQuery.isError
            ? "border-loss/40 text-loss"
            : status.active
              ? "border-profit/40 text-profit"
              : "border-border-default text-text-muted"}
          data-testid="runtime-status"
        >
          {statusQuery.isError ? "Unavailable" : status.active ? "Running" : "Stopped"}
        </Badge>
        <div className="flex-1" />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-6"
          onClick={refreshDitto}
          title="Refresh Ditto state"
          aria-label="Refresh Ditto state"
          data-testid="refresh-ditto"
        >
          <RefreshCw size={12} aria-hidden="true" />
        </Button>
        <a
          href="/ditto"
          className="inline-flex items-center gap-1 text-xxs text-accent hover:underline"
        >
          Manage <ExternalLink size={10} aria-hidden="true" />
        </a>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {(accountsQuery.isError || statusQuery.isError) && (
          <div className="m-3 flex items-start gap-2 rounded border border-loss/30 bg-loss/10 px-2 py-1.5 text-xs text-loss" role="alert">
            <AlertCircle size={13} className="mt-0.5 flex-none" aria-hidden="true" />
            <span>
              {accountsQuery.isError
                ? mutationError(accountsQuery.error)
                : mutationError(statusQuery.error)}
            </span>
          </div>
        )}

        <section className="space-y-2 border-b border-border-default px-3 py-2" aria-label="Mirror configuration">
          <div className="flex items-center gap-2">
            <label htmlFor="trade-copier-source" className="w-14 flex-none text-xs text-text-muted">
              Source
            </label>
            <Select value={sourceAccount} onValueChange={setSource} disabled={status.active || accountsQuery.isLoading}>
              <SelectTrigger id="trade-copier-source" className="h-7 flex-1 text-xs" aria-label="Source account">
                <SelectValue placeholder={accountsQuery.isLoading ? "Loading..." : "Select account"} />
              </SelectTrigger>
              <SelectContent data-testid="source-select">
                {activeAccounts.map((account) => (
                  <SelectItem key={account.id} value={account.id}>
                    {account.name}{account.is_master ? " (Master)" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center gap-2">
            <span className="w-14 flex-none text-xs text-text-muted">Mode</span>
            <div className="flex overflow-hidden rounded border border-border-default" role="group" aria-label="Allocation mode">
              {(Object.keys(MODE_LABELS) as MirrorMode[]).map((candidate) => (
                <button
                  key={candidate}
                  type="button"
                  onClick={() => setMode(candidate)}
                  disabled={status.active}
                  title={MODE_DESCRIPTIONS[candidate]}
                  aria-pressed={mode === candidate}
                  className={`px-2 py-1 text-xxs transition-colors disabled:cursor-not-allowed ${
                    mode === candidate ? "bg-accent/15 text-accent" : "text-text-muted hover:bg-surface-hover"
                  }`}
                  data-testid={`mode-${candidate}`}
                >
                  {MODE_LABELS[candidate]}
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="space-y-1.5 border-b border-border-default px-3 py-2" aria-label="Target accounts">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-primary">Target Accounts</span>
            <Badge variant="outline" className="text-xxs">{targetAccounts.size} selected</Badge>
          </div>

          {!accountsQuery.isLoading && accounts.length === 0 && (
            <div className="py-4 text-center text-xs text-text-muted">
              No Ditto accounts configured
            </div>
          )}

          {accounts.filter((account) => account.id !== sourceAccount).map((account) => {
            const enabled = account.status === "active";
            const selected = targetAccounts.has(account.id);
            return (
              <div
                key={account.id}
                className="flex items-center gap-2 rounded border border-border-default bg-surface-card px-2 py-1.5"
                data-testid={`target-${account.id}`}
              >
                <button
                  type="button"
                  className={`flex size-4 items-center justify-center rounded border ${
                    selected ? "border-accent bg-accent text-white" : "border-border-default text-transparent"
                  } disabled:cursor-not-allowed disabled:opacity-40`}
                  onClick={() => toggleTarget(account.id)}
                  disabled={!enabled || status.active}
                  aria-label={`${selected ? "Remove" : "Add"} ${account.name} ${selected ? "from" : "to"} targets`}
                  aria-pressed={selected}
                  data-testid={`select-target-${account.id}`}
                >
                  <Check size={11} aria-hidden="true" />
                </button>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs text-text-primary">{account.name}</div>
                  <div className="truncate text-xxs text-text-muted">
                    {account.group} · {account.allocation_weight}x · daily loss limit {formatCurrency(account.max_loss_daily)}
                  </div>
                </div>
                <Switch
                  checked={enabled}
                  onCheckedChange={(next) => accountMutation.mutate({ accountId: account.id, enabled: next })}
                  disabled={status.active || accountMutation.isPending}
                  aria-label={`${enabled ? "Disable" : "Enable"} ${account.name}`}
                  data-testid={`enable-${account.id}`}
                />
              </div>
            );
          })}
        </section>

        <section className="grid grid-cols-2 gap-2 border-b border-border-default px-3 py-2" aria-label="Ditto risk snapshot">
          <div>
            <div className="text-xxs text-text-muted">Aggregate capital</div>
            <div className="text-xs font-mono text-text-primary">
              {riskQuery.data ? formatCurrency(riskQuery.data.aggregate_capital) : "Unavailable"}
            </div>
          </div>
          <div>
            <div className="text-xxs text-text-muted">Today P&amp;L</div>
            <div className="text-xs font-mono text-text-primary">
              {riskQuery.data ? formatCurrency(riskQuery.data.aggregate_pnl) : "Unavailable"}
            </div>
          </div>
        </section>

        <section className="space-y-1 px-3 py-2" aria-label="Mirror activity">
          <div className="flex items-center justify-between text-xs">
            <span className="text-text-muted">Mirrored positions</span>
            <span className="font-mono text-text-primary">{status.mirrored_positions}</span>
          </div>
          <div className="flex items-center justify-between gap-3 text-xs">
            <span className="text-text-muted">Last sync</span>
            <span className="truncate font-mono text-text-primary">{status.last_sync ?? "Not yet"}</span>
          </div>
          {status.errors.map((error) => (
            <div key={error} className="flex items-start gap-1 text-xxs text-loss">
              <AlertCircle size={10} className="mt-0.5 flex-none" aria-hidden="true" />
              <span>{error}</span>
            </div>
          ))}
        </section>

        {actionError && (
          <p className="mx-3 mb-2 rounded border border-loss/30 bg-loss/10 px-2 py-1.5 text-xs text-loss" role="alert">
            {actionError}
          </p>
        )}
      </div>

      <div className="flex-none border-t border-border-default p-2">
        {status.active ? (
          <Button
            type="button"
            variant="destructive"
            size="sm"
            className="w-full"
            onClick={() => stopMutation.mutate()}
            disabled={isMutating}
            data-testid="stop-mirror"
          >
            <Square size={12} aria-hidden="true" />
            Stop Mirror
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            className="w-full"
            onClick={() => startMutation.mutate()}
            disabled={!canStart}
            data-testid="start-mirror"
          >
            <Play size={12} aria-hidden="true" />
            Start Mirror
          </Button>
        )}
      </div>
    </div>
  );
}

export default memo(TradeCopierWidget);
