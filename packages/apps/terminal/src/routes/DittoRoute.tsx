/**
 * DittoRoute — /ditto multi-account management.
 *
 * Three tabs:
 *   1. Accounts Overview — table of managed accounts with CRUD
 *   2. Position Mirror — source/target selection, allocation mode, start/stop
 *   3. Risk Dashboard — per-account margin, aggregate P&L, Kill All
 *
 * Visible only at advanced skill level (gated in TopBar nav).
 * Data fetched via TanStack Query from /ft-api/api/v1/ditto/* endpoints.
 */

import { useState, useCallback, useEffect, useRef, type FormEvent, type ReactNode } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Users,
  Copy,
  ShieldAlert,
  Plus,
  Power,
  PowerOff,
  Trash2,
  Play,
  Square,
  AlertTriangle,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Check,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import TabTransition from "@/components/motion/TabTransition";
import { cn } from "@/lib/utils";
import {
  getDittoAccounts,
  addDittoAccount,
  removeDittoAccount,
  setDittoAccountEnabled,
  getDittoMirrorStatus,
  startDittoMirror,
  stopDittoMirror,
  getDittoRisk,
  dittoKillAll,
  type DittoAccount,
  type DittoAccountCreatePayload,
  type MirrorStatus,
  type DittoRiskData,
} from "@/services/ftApi";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { BrokerRecommendations } from "@/components/account/BrokerRecommendations";
import { AccountStatusPanel } from "@/components/account/AccountStatusPanel";
import { BrokerRateLimitsPanel } from "@/components/account/BrokerRateLimitsPanel";

// ─── Tab registry ────────────────────────────────────────────────────────────

type TabId = "accounts" | "mirror" | "risk";

interface TabDef {
  id: TabId;
  label: string;
  icon: typeof Users;
}

const TABS: TabDef[] = [
  { id: "accounts", label: "Accounts", icon: Users },
  { id: "mirror", label: "Position Mirror", icon: Copy },
  { id: "risk", label: "Risk Dashboard", icon: ShieldAlert },
];

// ─── Formatting helpers ──────────────────────────────────────────────────────

function formatCurrency(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 10_000_000) return `${(value / 10_000_000).toFixed(2)} Cr`;
  if (abs >= 100_000) return `${(value / 100_000).toFixed(2)} L`;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

function pnlColor(value: number): string {
  if (value > 0) return "text-profit";
  if (value < 0) return "text-loss";
  return "text-text-muted";
}

// ─── Accounts tab ────────────────────────────────────────────────────────────

const ACCOUNTS_LOAD_TIMEOUT_MS = 5_000;

const DEFAULT_ACCOUNT_FORM = {
  accountId: "",
  openalgoHost: "",
  apiKey: "",
  name: "",
  group: "default",
  allocationWeight: "1",
  maxLossDaily: "50000",
  enabled: true,
  isMaster: false,
};

function BrokerOperationsPanels() {
  return (
    <>
      {/* Connected brokers + daily reauth status + OpenAlgo connection state */}
      <AccountStatusPanel />

      {/* Smart routing suggestions — which native broker for which job */}
      <BrokerRecommendations />

      {/* Per-broker API rate-limit controls */}
      <BrokerRateLimitsPanel />
    </>
  );
}

function AccountsTab() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["ditto", "accounts"],
    queryFn: getDittoAccounts,
    refetchInterval: 30_000,
    retry: 1,
  });

  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false);
  const [form, setForm] = useState(DEFAULT_ACCOUNT_FORM);
  const [formError, setFormError] = useState("");
  const [loadTimedOut, setLoadTimedOut] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const addMutation = useMutation({
    mutationFn: (account: DittoAccountCreatePayload) => addDittoAccount(account),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ditto", "accounts"] });
      queryClient.invalidateQueries({ queryKey: ["ditto", "risk"] });
      setIsAddDialogOpen(false);
      setForm(DEFAULT_ACCOUNT_FORM);
      setFormError("");
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ accountId, enabled }: { accountId: string; enabled: boolean }) =>
      setDittoAccountEnabled(accountId, enabled),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ditto", "accounts"] });
      queryClient.invalidateQueries({ queryKey: ["ditto", "risk"] });
    },
  });

  const removeMutation = useMutation({
    mutationFn: (accountId: string) => removeDittoAccount(accountId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ditto", "accounts"] });
      queryClient.invalidateQueries({ queryKey: ["ditto", "mirror"] });
      queryClient.invalidateQueries({ queryKey: ["ditto", "risk"] });
    },
  });

  useEffect(() => {
    if (isLoading) {
      setLoadTimedOut(false);
      timeoutRef.current = setTimeout(() => setLoadTimedOut(true), ACCOUNTS_LOAD_TIMEOUT_MS);
    } else {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      setLoadTimedOut(false);
    }
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [isLoading]);

  const accounts = data?.accounts ?? [];
  const actionError =
    (addMutation.error instanceof Error ? addMutation.error.message : "") ||
    (toggleMutation.error instanceof Error ? toggleMutation.error.message : "") ||
    (removeMutation.error instanceof Error ? removeMutation.error.message : "");

  function updateForm<K extends keyof typeof DEFAULT_ACCOUNT_FORM>(
    key: K,
    value: (typeof DEFAULT_ACCOUNT_FORM)[K],
  ) {
    setForm((current) => ({ ...current, [key]: value }));
    setFormError("");
  }

  function handleSubmitAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const allocationWeight = Number(form.allocationWeight);
    const maxLossDaily = Number(form.maxLossDaily);
    const payload: DittoAccountCreatePayload = {
      account_id: form.accountId.trim(),
      openalgo_host: form.openalgoHost.trim(),
      api_key: form.apiKey,
      name: form.name.trim(),
      group: form.group.trim() || "default",
      allocation_weight: allocationWeight,
      max_loss_daily: maxLossDaily,
      enabled: form.enabled,
      is_master: form.isMaster,
    };

    if (!payload.account_id || !payload.openalgo_host || !payload.api_key) {
      setFormError("Account ID, OpenAlgo URL, and API key are required.");
      return;
    }
    if (!Number.isFinite(allocationWeight) || allocationWeight <= 0) {
      setFormError("Allocation weight must be a positive number.");
      return;
    }
    if (!Number.isFinite(maxLossDaily) || maxLossDaily < 0) {
      setFormError("Max daily loss must be zero or greater.");
      return;
    }

    addMutation.mutate(payload);
  }

  const addAccountDialog = (
    <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
      <DialogContent className="max-w-xl bg-surface-card border-border-default">
        <form onSubmit={handleSubmitAccount} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Add Account</DialogTitle>
            <DialogDescription>
              Register an OpenAlgo-compatible account for mirroring and account-level risk controls.
            </DialogDescription>
          </DialogHeader>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="ditto-account-id">Account ID</Label>
              <Input
                id="ditto-account-id"
                value={form.accountId}
                onChange={(event) => updateForm("accountId", event.target.value)}
                placeholder="family_01"
                autoComplete="off"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ditto-name">Display Name</Label>
              <Input
                id="ditto-name"
                value={form.name}
                onChange={(event) => updateForm("name", event.target.value)}
                placeholder="Family Account"
                autoComplete="off"
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="ditto-openalgo-host">OpenAlgo URL</Label>
              <Input
                id="ditto-openalgo-host"
                value={form.openalgoHost}
                onChange={(event) => updateForm("openalgoHost", event.target.value)}
                placeholder="http://127.0.0.1:5001"
                autoComplete="url"
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="ditto-api-key">API Key</Label>
              <Input
                id="ditto-api-key"
                type="password"
                value={form.apiKey}
                onChange={(event) => updateForm("apiKey", event.target.value)}
                placeholder="OpenAlgo API key"
                autoComplete="off"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ditto-group">Group</Label>
              <Input
                id="ditto-group"
                value={form.group}
                onChange={(event) => updateForm("group", event.target.value)}
                placeholder="default"
                autoComplete="off"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ditto-allocation-weight">Allocation Weight</Label>
              <Input
                id="ditto-allocation-weight"
                type="number"
                min="0.01"
                step="0.01"
                value={form.allocationWeight}
                onChange={(event) => updateForm("allocationWeight", event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ditto-max-loss">Max Daily Loss</Label>
              <Input
                id="ditto-max-loss"
                type="number"
                min="0"
                step="100"
                value={form.maxLossDaily}
                onChange={(event) => updateForm("maxLossDaily", event.target.value)}
              />
            </div>
            <div className="flex items-center gap-4 self-end rounded border border-border-default bg-surface-base px-3 py-2">
              <label className="flex items-center gap-2 text-xs text-text-secondary">
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={(event) => updateForm("enabled", event.target.checked)}
                  className="size-3.5 accent-[var(--color-accent)]"
                />
                Enabled
              </label>
              <label className="flex items-center gap-2 text-xs text-text-secondary">
                <input
                  type="checkbox"
                  checked={form.isMaster}
                  onChange={(event) => updateForm("isMaster", event.target.checked)}
                  className="size-3.5 accent-[var(--color-accent)]"
                />
                Master
              </label>
            </div>
          </div>

          {(formError || addMutation.error) && (
            <p role="alert" className="text-xs text-loss">
              {formError || (addMutation.error instanceof Error ? addMutation.error.message : "Could not add account.")}
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setIsAddDialogOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={addMutation.isPending}>
              {addMutation.isPending ? <RefreshCw className="size-3.5 animate-spin" /> : <Plus className="size-3.5" />}
              Save Account
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );

  if (isLoading && !loadTimedOut) {
    return (
      <>
        <div className="flex items-center justify-center py-20">
          <RefreshCw className="size-5 text-text-muted animate-spin" />
          <span className="ml-2 text-sm text-text-muted">Loading accounts...</span>
        </div>
        {addAccountDialog}
      </>
    );
  }

  if (isError || loadTimedOut) {
    const message = isError
      ? (error?.message ?? "Unknown error")
      : "Request timed out — backend may not be running.";
    return (
      <>
        <div className="flex flex-col items-center justify-center py-20 gap-4">
          <AlertTriangle className="size-8 text-text-muted" />
          <p className="text-sm text-text-secondary text-center max-w-xs">
            Could not load accounts.{" "}
            <span className="text-text-muted">{message}</span>
          </p>
          <Button size="sm" variant="outline" onClick={() => { setLoadTimedOut(false); void refetch(); }}>
            <RefreshCw className="size-3.5" />
            Retry
          </Button>
        </div>
        {addAccountDialog}
      </>
    );
  }

  if (!isLoading && accounts.length === 0) {
    return (
      <div className="space-y-6">
        <BrokerOperationsPanels />
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <Users className="size-8 text-text-muted" />
          <p className="text-sm text-text-muted">No accounts connected</p>
          <p className="text-xs text-text-disabled">Add an account to get started.</p>
          <Button size="sm" variant="outline" onClick={() => setIsAddDialogOpen(true)}>
            <Plus className="size-3.5" />
            Add Account
          </Button>
        </div>
        {addAccountDialog}
      </div>
    );
  }

  const totalCapital = accounts.reduce((sum, a) => sum + a.capital, 0);
  const totalPnl = accounts.reduce((sum, a) => sum + a.pnl_today, 0);
  const activeCount = accounts.filter((a) => a.status === "active").length;

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <SummaryCard label="Total Capital" value={formatCurrency(totalCapital)} />
        <SummaryCard
          label="Today P&L"
          value={formatCurrency(totalPnl)}
          valueClass={pnlColor(totalPnl)}
        />
        <SummaryCard label="Active Accounts" value={`${activeCount} / ${accounts.length}`} />
      </div>

      <BrokerOperationsPanels />

      {/* Actions row */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-heading font-semibold text-text-primary">
          Managed Accounts
        </h2>
        <Button size="sm" variant="outline" onClick={() => setIsAddDialogOpen(true)}>
          <Plus className="size-3.5" />
          Add Account
        </Button>
      </div>
      {actionError && (
        <p role="alert" className="rounded border border-loss/30 bg-loss/10 px-3 py-2 text-xs text-loss">
          {actionError}
        </p>
      )}

      {/* Accounts table */}
      <div className="rounded-lg border border-border-default overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Broker</TableHead>
              <TableHead>Group</TableHead>
              <TableHead className="text-right">Capital</TableHead>
              <TableHead className="text-right">Today P&L</TableHead>
              <TableHead className="text-right">Positions</TableHead>
              <TableHead className="text-center">Status</TableHead>
              <TableHead className="text-center">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {accounts.map((account) => (
              <AccountRow
                key={account.id}
                account={account}
                isBusy={
                  toggleMutation.isPending || removeMutation.isPending
                }
                onSetEnabled={(accountId, enabled) =>
                  toggleMutation.mutate({ accountId, enabled })
                }
                onRemove={(accountId) => removeMutation.mutate(accountId)}
              />
            ))}
          </TableBody>
        </Table>
      </div>
      {addAccountDialog}
    </div>
  );
}

function AccountRow({
  account,
  isBusy,
  onSetEnabled,
  onRemove,
}: {
  account: DittoAccount;
  isBusy: boolean;
  onSetEnabled: (accountId: string, enabled: boolean) => void;
  onRemove: (accountId: string) => void;
}) {
  const isActive = account.status === "active";
  return (
    <TableRow>
      <TableCell className="font-medium">
        <div className="flex items-center gap-2">
          <span className="text-sm text-text-primary">{account.name}</span>
          {account.is_master && (
            <Badge variant="outline" className="text-xxs h-4 border-accent text-accent">
              Master
            </Badge>
          )}
        </div>
      </TableCell>
      <TableCell className="text-sm text-text-secondary">{account.broker}</TableCell>
      <TableCell>
        <Badge variant="outline" className="text-xxs h-5">
          {account.group}
        </Badge>
      </TableCell>
      <TableCell className="text-right font-mono text-sm text-text-primary">
        {formatCurrency(account.capital)}
      </TableCell>
      <TableCell className={cn("text-right font-mono text-sm", pnlColor(account.pnl_today))}>
        <span className="inline-flex items-center gap-1">
          {account.pnl_today > 0 && <TrendingUp className="size-3" />}
          {account.pnl_today < 0 && <TrendingDown className="size-3" />}
          {formatCurrency(account.pnl_today)}
        </span>
      </TableCell>
      <TableCell className="text-right font-mono text-sm text-text-secondary">
        {account.positions}
      </TableCell>
      <TableCell className="text-center">
        <Badge
          variant="outline"
          className={cn(
            "text-xxs h-5",
            account.status === "active"
              ? "border-profit/40 text-profit"
              : "border-text-muted/40 text-text-muted",
          )}
        >
          {account.status}
        </Badge>
      </TableCell>
      <TableCell className="text-center">
        <div className="flex items-center justify-center gap-1">
          <Button
            size="icon-xs"
            variant="ghost"
            aria-label={`Connect ${account.name}`}
            disabled={isBusy || isActive}
            onClick={() => onSetEnabled(account.id, true)}
          >
            <Power className="size-3" aria-hidden="true" />
          </Button>
          <Button
            size="icon-xs"
            variant="ghost"
            aria-label={`Disconnect ${account.name}`}
            disabled={isBusy || !isActive}
            onClick={() => onSetEnabled(account.id, false)}
          >
            <PowerOff className="size-3" aria-hidden="true" />
          </Button>
          <Button
            size="icon-xs"
            variant="ghost"
            aria-label={`Remove ${account.name}`}
            disabled={isBusy}
            onClick={() => onRemove(account.id)}
          >
            <Trash2 className="size-3" aria-hidden="true" />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

function SummaryCard({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-glass-inner border border-glass-l2 bg-glass-l2 p-4">
      <p className="text-xs text-text-muted mb-1">{label}</p>
      <p className={cn("text-lg font-mono font-semibold", valueClass ?? "text-text-primary")}>
        {value}
      </p>
    </div>
  );
}

// ─── Mirror tab ──────────────────────────────────────────────────────────────

function MirrorTab() {
  const queryClient = useQueryClient();

  const { data: accounts } = useQuery({
    queryKey: ["ditto", "accounts"],
    queryFn: getDittoAccounts,
  });

  const { data: mirrorStatus, isLoading } = useQuery({
    queryKey: ["ditto", "mirror", "status"],
    queryFn: getDittoMirrorStatus,
    refetchInterval: 10_000,
  });

  const [sourceAccount, setSourceAccount] = useState<string>("");
  const [targetAccounts, setTargetAccounts] = useState<Set<string>>(new Set());
  const [mirrorMode, setMirrorMode] = useState<string>("proportional");

  const startMutation = useMutation({
    mutationFn: () =>
      startDittoMirror(sourceAccount, Array.from(targetAccounts), mirrorMode),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ditto", "mirror"] });
    },
  });

  const stopMutation = useMutation({
    mutationFn: stopDittoMirror,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ditto", "mirror"] });
    },
  });

  const accountList = accounts?.accounts ?? [];
  const status: MirrorStatus = mirrorStatus ?? {
    active: false,
    source_account: null,
    target_accounts: [],
    mode: "proportional",
    mirrored_positions: 0,
    last_sync: null,
    errors: [],
  };

  const toggleTarget = useCallback(
    (id: string) => {
      setTargetAccounts((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
    },
    [],
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <RefreshCw className="size-5 text-text-muted animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Status indicator */}
      <div className="rounded-glass-inner border border-glass-l2 bg-glass-l2 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div
              className={cn(
                "size-3 rounded-full",
                status.active ? "bg-profit animate-pulse" : "bg-text-muted",
              )}
            />
            <div>
              <p className="text-sm font-medium text-text-primary">
                Mirror Status: {status.active ? "Active" : "Stopped"}
              </p>
              {status.active && (
                <p className="text-xs text-text-muted">
                  {status.mirrored_positions} positions mirrored
                  {status.last_sync ? ` — last sync: ${status.last_sync}` : ""}
                </p>
              )}
            </div>
          </div>
          {status.active && (
            <Button
              size="sm"
              variant="destructive"
              onClick={() => stopMutation.mutate()}
              disabled={stopMutation.isPending}
            >
              <Square className="size-3.5" />
              Stop Mirror
            </Button>
          )}
        </div>
      </div>

      {/* Configuration */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Source account */}
        <div className="space-y-2">
          <label className="text-xs font-medium text-text-secondary">Source Account (Master)</label>
          <Select value={sourceAccount} onValueChange={setSourceAccount}>
            <SelectTrigger>
              <SelectValue placeholder="Select source account" />
            </SelectTrigger>
            <SelectContent>
              {accountList
                .filter((a) => a.status === "active")
                .map((a) => (
                  <SelectItem key={a.id} value={a.id}>
                    {a.name} ({a.broker})
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
        </div>

        {/* Mirror mode */}
        <div className="space-y-2">
          <label className="text-xs font-medium text-text-secondary">Allocation Mode</label>
          <Select value={mirrorMode} onValueChange={setMirrorMode}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="proportional">Proportional (by capital)</SelectItem>
              <SelectItem value="fixed">Fixed (same quantity)</SelectItem>
              <SelectItem value="equal">Equal (split evenly)</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Target accounts multi-select */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-text-secondary">
          Target Accounts ({targetAccounts.size} selected)
        </label>
        <div className="rounded-lg border border-border-default divide-y divide-border-default">
          {accountList
            .filter((a) => a.status === "active" && a.id !== sourceAccount)
            .map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => toggleTarget(a.id)}
                className={cn(
                  "w-full flex items-center justify-between px-4 py-3 text-left transition-colors",
                  targetAccounts.has(a.id)
                    ? "bg-accent/5"
                    : "hover:bg-surface-hover",
                )}
              >
                <div className="flex items-center gap-3">
                  <div
                    className={cn(
                      "size-4 rounded border flex items-center justify-center",
                      targetAccounts.has(a.id)
                        ? "border-accent bg-accent"
                        : "border-border-default",
                    )}
                  >
                    {targetAccounts.has(a.id) && (
                      <Check className="size-3 text-white" aria-hidden="true" strokeWidth={2} />
                    )}
                  </div>
                  <div>
                    <p className="text-sm text-text-primary">{a.name}</p>
                    <p className="text-xs text-text-muted">
                      {a.broker} — Weight: {a.allocation_weight}x
                    </p>
                  </div>
                </div>
                <Badge variant="outline" className="text-xxs h-5">
                  {a.group}
                </Badge>
              </button>
            ))}
        </div>
      </div>

      {/* Start button */}
      {!status.active && (
        <Button
          onClick={() => startMutation.mutate()}
          disabled={
            !sourceAccount ||
            targetAccounts.size === 0 ||
            startMutation.isPending
          }
          className="w-full"
        >
          <Play className="size-4" />
          Start Position Mirroring
        </Button>
      )}

      {startMutation.isError && (
        <p className="text-sm text-loss">
          Failed to start mirror: {startMutation.error.message}
        </p>
      )}
    </div>
  );
}

// ─── Risk tab ────────────────────────────────────────────────────────────────

function RiskTab() {
  const [killDialogOpen, setKillDialogOpen] = useState(false);
  const queryClient = useQueryClient();

  const { data: riskData, isLoading } = useQuery({
    queryKey: ["ditto", "risk"],
    queryFn: getDittoRisk,
    refetchInterval: 15_000,
  });

  const killMutation = useMutation({
    mutationFn: dittoKillAll,
    onSuccess: () => {
      setKillDialogOpen(false);
      queryClient.invalidateQueries({ queryKey: ["ditto"] });
    },
  });

  const risk: DittoRiskData = riskData ?? {
    aggregate_pnl: 0,
    aggregate_capital: 0,
    accounts: [],
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <RefreshCw className="size-5 text-text-muted animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Aggregate summary */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <SummaryCard
          label="Aggregate P&L"
          value={formatCurrency(risk.aggregate_pnl)}
          valueClass={pnlColor(risk.aggregate_pnl)}
        />
        <SummaryCard label="Total Capital" value={formatCurrency(risk.aggregate_capital)} />
        <div className="rounded-lg border border-loss/30 bg-loss/5 p-4">
          <p className="text-xs text-loss mb-2">Emergency Action</p>
          <Button
            variant="destructive"
            size="sm"
            className="w-full"
            onClick={() => setKillDialogOpen(true)}
          >
            <AlertTriangle className="size-3.5" />
            Kill All Positions
          </Button>
        </div>
      </div>

      {/* Per-account risk table */}
      <div className="rounded-lg border border-border-default overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Account</TableHead>
              <TableHead className="text-right">Margin Used</TableHead>
              <TableHead className="text-right">Today P&L</TableHead>
              <TableHead className="text-right">Positions</TableHead>
              <TableHead className="text-center">Risk Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {risk.accounts.map((acct) => (
              <TableRow key={acct.id}>
                <TableCell className="text-sm font-medium text-text-primary">
                  {acct.name}
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center justify-end gap-2">
                    <div className="w-20 h-1.5 rounded-full bg-surface-hover overflow-hidden">
                      <div
                        className={cn(
                          "h-full rounded-full transition-[width]",
                          acct.margin_used_pct > 80
                            ? "bg-loss"
                            : acct.margin_used_pct > 60
                              ? "bg-yellow-500"
                              : "bg-profit",
                        )}
                        style={{ width: `${Math.min(acct.margin_used_pct, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs font-mono text-text-secondary w-12 text-right">
                      {acct.margin_used_pct.toFixed(1)}%
                    </span>
                  </div>
                </TableCell>
                <TableCell
                  className={cn("text-right font-mono text-sm", pnlColor(acct.pnl_today))}
                >
                  {formatCurrency(acct.pnl_today)}
                </TableCell>
                <TableCell className="text-right font-mono text-sm text-text-secondary">
                  {acct.positions}
                </TableCell>
                <TableCell className="text-center">
                  <RiskBadge status={acct.risk_status} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Kill-all confirmation dialog */}
      <Dialog open={killDialogOpen} onOpenChange={setKillDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-loss">
              <AlertTriangle className="size-5" />
              Kill All Positions
            </DialogTitle>
            <DialogDescription>
              This will close ALL open positions across ALL managed accounts immediately.
              This action cannot be undone. Are you sure?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setKillDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => killMutation.mutate()}
              disabled={killMutation.isPending}
            >
              {killMutation.isPending ? "Killing..." : "Confirm Kill All"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function RiskBadge({ status }: { status: string }) {
  const config: Record<string, { class: string; label: string }> = {
    OK: { class: "border-profit/40 text-profit", label: "OK" },
    WARNING: { class: "border-yellow-500/40 text-yellow-500", label: "Warning" },
    CRITICAL: { class: "border-loss/40 text-loss", label: "Critical" },
    PAUSED: { class: "border-text-muted/40 text-text-muted", label: "Paused" },
  };
  const c = config[status] ?? config["OK"];
  return (
    <Badge variant="outline" className={cn("text-xxs h-5", c.class)}>
      {c.label}
    </Badge>
  );
}

// ─── Tab content map ─────────────────────────────────────────────────────────

const TAB_CONTENT: Record<TabId, ReactNode> = {
  accounts: <AccountsTab />,
  mirror: <MirrorTab />,
  risk: <RiskTab />,
};

// ─── Route export ────────────────────────────────────────────────────────────

export default function DittoRoute() {
  const [activeTab, setActiveTab] = useState<TabId>("accounts");

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-glass-chrome bg-glass-chrome backdrop-blur-md shrink-0">
        {/* Title row */}
        <div className="flex items-center justify-between px-6 pt-4 pb-3">
          <div className="flex items-center gap-3">
            <Users className="w-5 h-5 text-accent" />
            <div>
              <h1 className="font-heading font-bold text-base text-text-primary">
                Account Manager
              </h1>
              <p className="text-xxs text-text-muted">
                Manage connected accounts, mirror positions, and monitor risk across accounts
              </p>
            </div>
          </div>
        </div>

        {/* Tab bar */}
        <div
          role="tablist"
          aria-label="Account Manager sections"
          className="flex items-end gap-1 px-6 overflow-x-auto scrollbar-none"
        >
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                role="tab"
                aria-selected={isActive}
                aria-controls={`ditto-tabpanel-${tab.id}`}
                id={`ditto-tab-${tab.id}`}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-2 text-xs font-sans font-medium transition-colors border-b-2 whitespace-nowrap shrink-0",
                  isActive
                    ? "text-accent border-accent"
                    : "text-text-secondary hover:text-text-primary border-transparent hover:border-border-default",
                )}
              >
                <Icon className="w-3.5 h-3.5 shrink-0" />
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Content */}
      <div
        role="tabpanel"
        id={`ditto-tabpanel-${activeTab}`}
        aria-labelledby={`ditto-tab-${activeTab}`}
        className="flex-1"
      >
        <ScrollArea className="h-full">
          <TabTransition tabKey={activeTab}>
            <div className="p-6 max-w-5xl mx-auto">{TAB_CONTENT[activeTab]}</div>
          </TabTransition>
        </ScrollArea>
      </div>
    </div>
  );
}
