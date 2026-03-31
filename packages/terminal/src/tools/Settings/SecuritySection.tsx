/**
 * SecuritySection — banned IP management and threat statistics.
 *
 * APIs:
 *   GET  /ft-api/api/v1/security/stats  → threat overview counters
 *   GET  /ft-api/api/v1/security/bans   → list of banned IPs
 *   POST /ft-api/api/v1/security/ban    → ban an IP
 *   POST /ft-api/api/v1/security/unban  → unban an IP
 */

import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ShieldOff,
  ShieldCheck,
  RefreshCw,
  AlertTriangle,
  Ban,
} from "lucide-react";
import { SectionTitle, TextInput, Toggle } from "./shared";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  getSecurityStats,
  getBannedIPs,
  banIP,
  unbanIP,
  getSecuritySettings,
  updateSecuritySettings,
  type SecurityStats,
  type BannedIP,
  type SecuritySettings,
} from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Stat tile
// ---------------------------------------------------------------------------

function StatTile({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: "warning" | "loss";
}) {
  const color =
    accent === "loss"
      ? "text-loss"
      : accent === "warning"
        ? "text-warning"
        : "text-text-primary";
  return (
    <div className="flex flex-col gap-0.5 p-3 rounded bg-surface-card border border-border-default">
      <span className="text-xxs text-text-muted uppercase tracking-wider">{label}</span>
      <span className={`font-mono tabular-nums font-bold text-lg leading-tight ${color}`}>
        {value.toLocaleString("en-IN")}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main section
// ---------------------------------------------------------------------------

export function SecuritySection() {
  const qc = useQueryClient();
  const [newIp, setNewIp]       = useState("");
  const [newReason, setNewReason] = useState("");
  const [banError, setBanError]  = useState<string | null>(null);
  const [sortField, setSortField] = useState<"ip" | "reason" | "banned_at">("banned_at");
  const [sortAsc, setSortAsc]     = useState(false);

  const statsQuery = useQuery<SecurityStats>({
    queryKey: ["ft", "security", "stats"],
    queryFn: getSecurityStats,
    refetchInterval: 30_000,
  });

  const bansQuery = useQuery<{ bans: BannedIP[] }>({
    queryKey: ["ft", "security", "bans"],
    queryFn: getBannedIPs,
    refetchInterval: 30_000,
  });

  const settingsQuery = useQuery<SecuritySettings>({
    queryKey: ["ft", "security", "settings"],
    queryFn: getSecuritySettings,
    staleTime: 60_000,
    retry: 1,
  });

  const autoBanMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      updateSecuritySettings({ auto_ban_enabled: enabled }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["ft", "security", "settings"] });
    },
  });

  const banMutation = useMutation({
    mutationFn: ({ ip, reason }: { ip: string; reason: string }) =>
      banIP(ip, reason),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["ft", "security"] });
      setNewIp("");
      setNewReason("");
      setBanError(null);
    },
    onError: (err) => {
      setBanError(err instanceof Error ? err.message : "Ban failed");
    },
  });

  const unbanMutation = useMutation({
    mutationFn: (ip: string) => unbanIP(ip),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["ft", "security"] });
    },
  });

  const handleBan = useCallback(() => {
    const ip = newIp.trim();
    if (!ip) {
      setBanError("IP address is required");
      return;
    }
    const ipv4Regex = /^(\d{1,3}\.){3}\d{1,3}$/;
    const ipv6Regex = /^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$/;
    if (!ipv4Regex.test(ip) && !ipv6Regex.test(ip)) {
      setBanError("Invalid IP address format");
      return;
    }
    banMutation.mutate({ ip, reason: newReason.trim() || "Manual ban" });
  }, [newIp, newReason, banMutation]);

  const stats = statsQuery.data;
  const rawBans = bansQuery.data?.bans ?? [];
  const bans = [...rawBans].sort((a, b) => {
    const aVal = a[sortField];
    const bVal = b[sortField];
    const cmp = String(aVal).localeCompare(String(bVal));
    return sortAsc ? cmp : -cmp;
  });
  const autoBanEnabled = settingsQuery.data?.auto_ban_enabled ?? false;

  // ---------------------------------------------------------------------------
  // Format ban time relative to now
  // ---------------------------------------------------------------------------
  function fmtAge(isoStr: string): string {
    const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  return (
    <div className="space-y-6">
      <SectionTitle>Security</SectionTitle>

      {/* Stats grid */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">
          Threat Statistics
        </p>

        {statsQuery.isLoading && (
          <div className="flex items-center gap-2 text-xs text-text-muted">
            <RefreshCw size={12} className="animate-spin" />
            Loading…
          </div>
        )}

        {statsQuery.isError && (
          <div className="flex items-center gap-2 text-xs text-warning">
            <AlertTriangle size={12} />
            Backend unreachable — stats unavailable
          </div>
        )}

        {stats && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatTile label="Total Requests" value={stats.total_requests} />
            <StatTile
              label="Failed Auths"
              value={stats.failed_auths}
              accent={stats.failed_auths > 0 ? "warning" : undefined}
            />
            <StatTile
              label="404s"
              value={stats.not_found_count}
              accent={stats.not_found_count > 50 ? "warning" : undefined}
            />
            <StatTile
              label="Banned IPs"
              value={stats.banned_count}
              accent={stats.banned_count > 0 ? "loss" : undefined}
            />
          </div>
        )}
      </div>

      {/* Auto-ban toggle */}
      <div className="rounded border border-border-default bg-surface-card p-4 space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          Automatic Banning
        </p>
        <Toggle
          checked={autoBanEnabled}
          onChange={(checked) => autoBanMutation.mutate(checked)}
          label={autoBanEnabled ? "Auto-ban is enabled" : "Auto-ban is disabled"}
        />
        <p className="text-xxs text-text-muted">
          When enabled, IPs that exceed configured thresholds (404 probes,
          failed API calls) are automatically banned. Managed by the FT backend.
        </p>
      </div>

      {/* Banned IPs table */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            Banned IPs
          </p>
          <button
            type="button"
            onClick={() => void qc.invalidateQueries({ queryKey: ["ft", "security"] })}
            className="flex items-center gap-1 text-xxs text-text-muted hover:text-text-secondary transition-colors"
            aria-label="Refresh banned IPs"
          >
            <RefreshCw
              size={10}
              className={bansQuery.isFetching ? "animate-spin" : ""}
            />
            Refresh
          </button>
        </div>

        {bansQuery.isLoading && (
          <div className="flex items-center gap-2 text-xs text-text-muted">
            <RefreshCw size={12} className="animate-spin" />
            Loading…
          </div>
        )}

        {bansQuery.isError && (
          <div className="flex items-center gap-2 text-xs text-warning">
            <AlertTriangle size={12} />
            Backend unreachable — ban list unavailable
          </div>
        )}

        {!bansQuery.isLoading && !bansQuery.isError && bans.length === 0 && (
          <div className="flex items-center gap-2 p-3 rounded bg-surface-card border border-border-default text-xs text-text-muted">
            <ShieldCheck size={13} className="text-profit" />
            No banned IPs
          </div>
        )}

        {bans.length > 0 && (
          <div className="rounded border border-border-default overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border-default bg-surface-card">
                  {([["ip", "IP Address"], ["reason", "Reason"], ["banned_at", "Banned"]] as const).map(([field, label]) => (
                    <th
                      key={field}
                      className="px-3 py-1.5 text-left text-text-muted font-medium cursor-pointer select-none hover:text-text-secondary transition-colors"
                      onClick={() => {
                        if (sortField === field) setSortAsc(!sortAsc);
                        else { setSortField(field); setSortAsc(true); }
                      }}
                    >
                      {label}{sortField === field ? (sortAsc ? " \u25B2" : " \u25BC") : ""}
                    </th>
                  ))}
                  <th className="px-3 py-1.5 text-right text-text-muted font-medium">Action</th>
                </tr>
              </thead>
              <tbody>
                {bans.map((ban) => (
                  <tr
                    key={ban.ip}
                    className="border-b border-border-default last:border-0 hover:bg-surface-hover transition-colors"
                  >
                    <td className="px-3 py-1.5 font-mono text-text-primary">{ban.ip}</td>
                    <td className="px-3 py-1.5 text-text-secondary">
                      <Badge
                        variant="outline"
                        className="text-xxs px-1.5 py-0 border-border-default text-text-muted"
                      >
                        {ban.reason}
                      </Badge>
                    </td>
                    <td className="px-3 py-1.5 text-text-muted tabular-nums">
                      {fmtAge(ban.banned_at)}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      <button
                        type="button"
                        onClick={() => unbanMutation.mutate(ban.ip)}
                        disabled={unbanMutation.isPending}
                        className="text-xxs text-accent hover:underline disabled:opacity-50"
                        aria-label={`Unban ${ban.ip}`}
                      >
                        Unban
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Ban IP form */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">
          Ban an IP
        </p>
        <div className="space-y-2">
          <TextInput
            value={newIp}
            onChange={setNewIp}
            placeholder="e.g. 192.168.1.100"
            aria-label="IP address to ban"
          />
          <TextInput
            value={newReason}
            onChange={setNewReason}
            placeholder="Reason (optional)"
            aria-label="Reason for ban"
          />
          {banError && (
            <p className="text-xxs text-loss">{banError}</p>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={handleBan}
            disabled={banMutation.isPending || !newIp.trim()}
            className="flex items-center gap-1.5 text-xs h-7 border-loss/40 text-loss hover:bg-loss/10 hover:text-loss"
          >
            {banMutation.isPending ? (
              <RefreshCw size={11} className="animate-spin" />
            ) : (
              <Ban size={11} />
            )}
            {banMutation.isPending ? "Banning…" : "Ban IP"}
          </Button>
        </div>
      </div>

      {/* Notice */}
      <div className="flex items-start gap-2 p-3 rounded bg-surface-card border border-border-default text-xs text-text-muted">
        <ShieldOff size={12} className="shrink-0 mt-0.5 text-warning" />
        <span>
          IP bans block requests at the FlintTrade backend layer only. They do not
          affect OpenAlgo or your broker connection.
        </span>
      </div>
    </div>
  );
}
