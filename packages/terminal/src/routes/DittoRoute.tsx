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

import { useState, useCallback, useEffect, useRef, type ReactNode } from "react";
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
  getDittoMirrorStatus,
  startDittoMirror,
  stopDittoMirror,
  getDittoRisk,
  dittoKillAll,
  type DittoAccount,
  type MirrorStatus,
  type DittoRiskData,
} from "@/services/ftApi";

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

function AccountsTab() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["ditto", "accounts"],
    queryFn: getDittoAccounts,
    refetchInterval: 30_000,
    retry: 1,
  });

  const [loadTimedOut, setLoadTimedOut] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  if (isLoading && !loadTimedOut) {
    return (
      <div className="flex items-center justify-center py-20">
        <RefreshCw className="size-5 text-text-muted animate-spin" />
        <span className="ml-2 text-sm text-text-muted">Loading accounts...</span>
      </div>
    );
  }

  if (isError || loadTimedOut) {
    const message = isError
      ? (error?.message ?? "Unknown error")
      : "Request timed out — backend may not be running.";
    return (
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
    );
  }

  if (!isLoading && accounts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <Users className="size-8 text-text-muted" />
        <p className="text-sm text-text-muted">No accounts connected</p>
        <p className="text-xs text-text-disabled">Add an account to get started.</p>
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

      {/* Actions row */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-heading font-semibold text-text-primary">
          Managed Accounts
        </h2>
        <Button size="sm" variant="outline" disabled>
          <Plus className="size-3.5" />
          Add Account
        </Button>
      </div>

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
              <AccountRow key={account.id} account={account} />
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function AccountRow({ account }: { account: DittoAccount }) {
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
          <Button size="icon-xs" variant="ghost" aria-label="Connect account" disabled>
            <Power className="size-3" aria-hidden="true" />
          </Button>
          <Button size="icon-xs" variant="ghost" aria-label="Disconnect account" disabled>
            <PowerOff className="size-3" aria-hidden="true" />
          </Button>
          <Button size="icon-xs" variant="ghost" aria-label="Remove account" disabled>
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
                      <svg className="size-3 text-white" viewBox="0 0 12 12" fill="none">
                        <path d="M3 6l2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
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
                Multi-Account Manager
              </h1>
              <p className="text-xxs text-text-muted">
                Manage clients, mirror positions, and monitor risk across accounts
              </p>
            </div>
          </div>
        </div>

        {/* Tab bar */}
        <div
          role="tablist"
          aria-label="Ditto sections"
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
