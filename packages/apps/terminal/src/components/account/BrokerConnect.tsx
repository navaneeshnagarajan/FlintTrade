/**
 * BrokerConnect — shared native broker connect surface.
 *
 * Lets the operator connect catalogue-backed native brokers using their
 * preferred login method. The method catalogue + form fields come from the
 * backend (`/native/brokers`), so the UI stays in lockstep with what each
 * adapter supports. Credentials are POSTed to the local backend only. OAuth
 * opens the broker's approval page in a new tab; the backend's loopback callback
 * establishes the session.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  CheckCircle2,
  XCircle,
  Loader2,
  Trash2,
  ExternalLink,
  AlertTriangle,
  RefreshCw,
  Copy,
  Star,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { BROKER_ACCOUNTS_QUERY_KEY, useBrokerAccounts } from "@/hooks/useBrokerAccounts";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import type { BrokerAccount } from "@/types/broker";
import {
  reconnectBrokerAccount,
  removeBrokerAccount,
  setPrimaryBrokerAccount,
} from "@/services/brokerAccountsApi";
import {
  listNativeBrokers,
  listBrokerMcpCatalogue,
  connectNativeAccount,
  oauthStartNativeAccount,
  type BrokerSdkAttestation,
  type McpClientConfig,
  type NativeAuthMethod,
  type NativeBroker,
} from "@/services/ftApi.native";

const BROKERS_KEY = ["native", "brokers"] as const;
const MCP_KEY = ["broker", "mcp"] as const;

function expiryLabel(expiresAt?: number | null): string {
  if (!expiresAt) return "";
  const ms = expiresAt * 1000 - Date.now();
  if (ms <= 0) return "expired";
  const hours = Math.floor(ms / 3_600_000);
  const mins = Math.floor((ms % 3_600_000) / 60_000);
  return hours > 0 ? `expires in ${hours}h ${mins}m` : `expires in ${mins}m`;
}

function mcpCommand(config: McpClientConfig): string {
  if (!config.command) return "";
  return [config.command, ...(config.args ?? [])].join(" ");
}

function mcpConfigJson(config: McpClientConfig): string {
  if (!config.config || Object.keys(config.config).length === 0) return "";
  return JSON.stringify(config.config, null, 2);
}

function joinBrokerNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  return `${names.slice(0, -1).join(", ")}, and ${names[names.length - 1]}`;
}

function blockerLabel(blockers: string[]): string {
  return joinBrokerNames(blockers);
}

function sdkStatusLabel(broker: NativeBroker): string {
  const attestation: BrokerSdkAttestation | null | undefined = broker.sdk_attestation;
  if (!attestation) return "SDK status unknown";
  if (attestation.status === "not_required") return "REST-native; no third-party SDK";
  const pin = attestation.pin ?? broker.sdk_pin ?? "SDK";
  const pinned = attestation.pinned_version ? ` ${attestation.pinned_version}` : "";
  const installed = attestation.installed_version ? ` installed ${attestation.installed_version}` : "";
  switch (attestation.status) {
    case "ok":
      return `${pin}${pinned} OK`;
    case "missing":
      return `${pin}${pinned} missing`;
    case "mismatch":
      return `${pin}${pinned}${installed} mismatch`;
    case "skipped":
      return `${pin} not yet pinned`;
    default:
      return `${pin} status unknown`;
  }
}

function sdkStatusTone(status?: BrokerSdkAttestation["status"] | null): string {
  if (status === "ok" || status === "not_required") return "border-profit/40 text-profit";
  if (status === "missing" || status === "mismatch") return "border-loss/40 text-loss";
  return "border-warning/40 text-warning";
}

function sdkReadyForConnect(broker: NativeBroker): boolean {
  const status = broker.sdk_attestation?.status;
  if (!status) return true;
  return status === "ok" || status === "not_required";
}

function canPromotePrimaryAccount(account: BrokerAccount): boolean {
  return account.status === "connected" && !account.is_primary && account.read_only !== true;
}

function McpSetupValue({
  label,
  copyLabel,
  value,
  multiline = false,
  onCopy,
}: {
  label: string;
  copyLabel: string;
  value: string;
  multiline?: boolean;
  onCopy: (label: string, value: string) => void | Promise<void>;
}) {
  return (
    <div className="grid grid-cols-[1fr_auto] items-start gap-2">
      <div className="min-w-0">
        <Label className="mb-1.5 block text-xs text-text-secondary">{label}</Label>
        {multiline ? (
          <pre
            aria-label={`${copyLabel} value`}
            className="max-h-36 min-h-9 overflow-auto rounded-md border border-border-default bg-surface-elevated px-3 py-2 font-mono text-xs leading-relaxed text-text-primary whitespace-pre-wrap break-words"
          >
            {value}
          </pre>
        ) : (
          <code
            aria-label={`${copyLabel} value`}
            className="block min-h-9 rounded-md border border-border-default bg-surface-elevated px-3 py-2 font-mono text-xs text-text-primary break-all"
          >
            {value}
          </code>
        )}
      </div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-label={`Copy ${copyLabel}`}
        onClick={() => {
          void onCopy(copyLabel, value);
        }}
      >
        <Copy className="size-4" aria-hidden="true" />
      </Button>
    </div>
  );
}

export function BrokerConnect() {
  const qc = useQueryClient();
  const brokersQuery = useQuery({ queryKey: BROKERS_KEY, queryFn: listNativeBrokers });
  const mcpQuery = useQuery({ queryKey: MCP_KEY, queryFn: listBrokerMcpCatalogue });
  useBrokerAccounts();
  const brokerAccounts = useBrokerStore((s) => s.accounts);

  const brokers = brokersQuery.data ?? [];
  const mcpBrokers = mcpQuery.data ?? [];
  const accounts = brokerAccounts.filter((a) => a.source === "native");
  const gatewayAccounts = brokerAccounts.filter((a) => a.source !== "native");
  const connectableNativeNames = brokers
    .filter((b) => b.connectable)
    .map((b) => b.display_name);
  const connectableNativeLabel = joinBrokerNames(connectableNativeNames);
  const unavailableNativeNames = brokers
    .filter((b) => !b.connectable)
    .map((b) => b.display_name);
  const unavailableNativeLabel = joinBrokerNames(unavailableNativeNames);
  const unavailableNativeVerb = unavailableNativeNames.length === 1 ? "stays" : "stay";
  const unavailableNativeBlockers = brokers
    .filter((b) => !b.connectable && b.native_connect_blockers.length > 0);
  const [selectedBroker, setSelectedBroker] = useState<string>("");
  const [selectedMethodId, setSelectedMethodId] = useState<string>("");
  const [accountId, setAccountId] = useState<string>("");
  const [accountLabel, setAccountLabel] = useState<string>("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState<string>("");
  const [notice, setNotice] = useState<string>("");

  const broker = brokers.find((b) => b.adapter_id === selectedBroker);
  const method: NativeAuthMethod | undefined = broker?.auth_methods.find((m) => m.id === selectedMethodId);
  const brokerConnectable = broker?.connectable ?? false;
  const brokerSdkReady = broker ? sdkReadyForConnect(broker) : false;
  const oauthRedirectUri = broker?.oauth_redirect_uri ?? "http://127.0.0.1:5100/api/v1/native/oauth/callback";
  const brokerPostbackUri = broker?.postback_uri ?? (
    selectedBroker ? `http://127.0.0.1:5100/api/v1/native/postbacks/${selectedBroker}` : ""
  );

  function resetForm() {
    setFields({});
    setAccountId("");
    setAccountLabel("");
    setError("");
    setNotice("");
  }

  function invalidateAccountQueries(delay = 0) {
    const refresh = () => {
      void qc.invalidateQueries({ queryKey: BROKER_ACCOUNTS_QUERY_KEY });
    };
    if (delay > 0) {
      setTimeout(refresh, delay);
    } else {
      refresh();
    }
  }

  function dropRemovedAccountEverywhere(ref: {
    source: "gateway" | "native";
    broker: string;
    account_id: string;
  }) {
    const key = brokerAccountKey(ref);
    // Drop from the store immediately so the next account poll's last-good
    // preservation cannot resurrect a just-removed account as a live write
    // target while its source refreshes.
    useBrokerStore.getState().removeAccount(key);
    // Also evict from the TanStack cache: until the invalidated refetch
    // resolves, a freshly-mounting useBrokerAccounts consumer would otherwise
    // sync the pre-removal snapshot back into the store, transiently
    // re-listing the removed account as connected.
    qc.setQueryData<BrokerAccount[]>(
      BROKER_ACCOUNTS_QUERY_KEY,
      (cached) => cached?.filter((a) => brokerAccountKey(a) !== key),
    );
    invalidateAccountQueries();
  }

  const connectMutation = useMutation({
    mutationFn: async () => {
      if (!broker || !method) throw new Error("Pick a broker and a login method.");
      if (!broker.connectable) throw new Error(`${broker.display_name} native connect is coming soon.`);
      if (!sdkReadyForConnect(broker)) {
        throw new Error(`${broker.display_name} native SDK is not ready (${sdkStatusLabel(broker)}).`);
      }
      if (!accountId.trim()) throw new Error("Enter an account ID / client code.");
      for (const f of method.fields) {
        if (f.required && !fields[f.name]?.trim()) throw new Error(`${f.label} is required.`);
      }
      const label = accountLabel.trim();
      if (method.kind === "oauth") {
        const payload = {
          adapter_id: broker.adapter_id,
          account_id: accountId.trim(),
          api_key: fields.api_key ?? "",
          api_secret: fields.api_secret ?? "",
          ...(label ? { label } : {}),
        };
        const started = await oauthStartNativeAccount(payload);
        window.open(started.auth_url, "_blank", "noopener");
        const postback = started.postback_uri ?? brokerPostbackUri;
        return {
          oauth: true,
          message: (
            `Approve access in the new tab. Use redirect ${started.redirect_uri}. ` +
            `Postback ${postback} is optional and needs a broker-reachable public or tunnel URL.`
          ),
        };
      }
      const result = await connectNativeAccount({
        adapter_id: broker.adapter_id,
        account_id: accountId.trim(),
        ...(label ? { label } : {}),
        credentials: {
          ...(method.credential_defaults ?? {}),
          ...Object.fromEntries(method.fields.map((f) => [f.name, fields[f.name] ?? ""])),
        },
      });
      // A failed connect is a non-2xx that already threw the backend message
      // inside connectNativeAccount; a 2xx always carries connected:true.
      if (!result.connected) throw new Error("Login did not establish a session.");
      return { oauth: false, message: `${broker.display_name} account ${accountId.trim()} connected.` };
    },
    onSuccess: (r) => {
      setError("");
      if (!r.oauth) {
        setFields({});
        setAccountId("");
        setAccountLabel("");
      }
      setNotice(r.message);
      // OAuth completes out-of-band in the callback tab; refresh accounts shortly after.
      if (r.oauth) invalidateAccountQueries(4000);
      invalidateAccountQueries();
    },
    onError: (e: unknown) => {
      setNotice("");
      setError(e instanceof Error ? e.message : "Connection failed.");
    },
  });

  async function copySetupUrl(label: string, value: string) {
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard API unavailable");
      }
      await navigator.clipboard.writeText(value);
      setError("");
      setNotice(`${label} copied.`);
    } catch {
      setNotice("");
      setError(`${label} could not be copied. Select and copy it manually.`);
    }
  }

  const removeMutation = useMutation({
    mutationFn: (sel: { adapter: string; account: string }) =>
      removeBrokerAccount({ source: "native", broker: sel.adapter, account_id: sel.account }),
    onSuccess: (_r, sel) => {
      setError("");
      setNotice(`${sel.adapter} account ${sel.account} disconnected.`);
      dropRemovedAccountEverywhere({
        source: "native", broker: sel.adapter, account_id: sel.account,
      });
    },
    onError: (e: unknown, sel) => {
      setNotice("");
      setError(
        e instanceof Error
          ? e.message
          : `Could not disconnect ${sel.adapter} account ${sel.account}.`,
      );
    },
  });

  const setPrimaryMutation = useMutation({
    mutationFn: (sel: { adapter: string; account: string }) =>
      setPrimaryBrokerAccount({ source: "native", broker: sel.adapter, account_id: sel.account }),
    onSuccess: (_r, sel) => {
      setError("");
      setNotice(`${sel.adapter} account ${sel.account} set as primary.`);
      invalidateAccountQueries();
    },
    onError: (e: unknown, sel) => {
      setNotice("");
      setError(
        e instanceof Error
          ? e.message
          : `Could not set ${sel.adapter} account ${sel.account} as primary.`,
      );
    },
  });

  const reloginMutation = useMutation({
    // Replay the stored (replayable) material first — a one-click morning
    // re-auth for accounts whose vault token is still valid (G5).
    mutationFn: (sel: { adapter: string; account: string }) =>
      reconnectBrokerAccount({ source: "native", broker: sel.adapter, account_id: sel.account }),
    onSuccess: (_r, sel) => {
      setError("");
      setNotice(`${sel.adapter} account ${sel.account} re-authenticated.`);
      invalidateAccountQueries();
    },
    onError: (e: unknown, sel) => {
      // Stored material is stale (single-use TOTP/OAuth code, expired token) —
      // prefill the connect form so the operator only enters what's missing.
      setSelectedBroker(sel.adapter);
      const first = brokers.find((b) => b.adapter_id === sel.adapter)?.auth_methods[0]?.id ?? "";
      setSelectedMethodId(first);
      setFields({});
      setAccountId(sel.account);
      setAccountLabel("");
      setNotice("");
      setError(
        e instanceof Error
          ? `${e.message} Enter fresh credentials below to re-authenticate.`
          : "Re-login failed — enter fresh credentials below.",
      );
    },
  });

  const gatewayRemoveMutation = useMutation({
    mutationFn: (sel: { accountId: string; broker: string }) =>
      removeBrokerAccount({ source: "gateway", broker: sel.broker, account_id: sel.accountId }),
    onSuccess: (_r, sel) => {
      setError("");
      setNotice(`Gateway account ${sel.accountId} disconnected.`);
      // Source-qualified key, never the bare id: isBrokerAccountMatch also
      // matches on account_id alone, so a bare id would cross-evict a native
      // row sharing this broker-supplied client code (dual-linked account).
      dropRemovedAccountEverywhere({
        source: "gateway", broker: sel.broker, account_id: sel.accountId,
      });
    },
    onError: (e: unknown, sel) => {
      setNotice("");
      setError(e instanceof Error ? e.message : `Could not disconnect gateway account ${sel.accountId}.`);
    },
  });

  const gatewayReconnectMutation = useMutation({
    mutationFn: (sel: { accountId: string; broker: string }) =>
      reconnectBrokerAccount({ source: "gateway", broker: sel.broker, account_id: sel.accountId }),
    onSuccess: (_r, sel) => {
      setError("");
      setNotice(`Gateway account ${sel.accountId} reconnected.`);
      invalidateAccountQueries();
    },
    onError: (e: unknown, sel) => {
      setNotice("");
      setError(e instanceof Error ? e.message : `Could not reconnect gateway account ${sel.accountId}.`);
    },
  });

  const gatewaySetPrimaryMutation = useMutation({
    mutationFn: (sel: { accountId: string; broker: string }) =>
      setPrimaryBrokerAccount({ source: "gateway", broker: sel.broker, account_id: sel.accountId }),
    onSuccess: (_r, sel) => {
      setError("");
      setNotice(`Gateway account ${sel.accountId} set as primary.`);
      invalidateAccountQueries();
    },
    onError: (e: unknown, sel) => {
      setNotice("");
      setError(e instanceof Error ? e.message : `Could not set gateway account ${sel.accountId} as primary.`);
    },
  });

  const gatewayBusy =
    gatewayRemoveMutation.isPending
    || gatewayReconnectMutation.isPending
    || gatewaySetPrimaryMutation.isPending;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-heading font-semibold text-base text-text-primary mb-1">Brokers</h2>
        <p className="text-sm text-text-muted">
          Connect your broker accounts. Pick the login method you prefer for each broker — credentials
          go only to your local FlintTrade backend.
        </p>
      </div>

      <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm text-text-secondary">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
        <div className="space-y-2">
          <p>
            <strong className="text-text-primary">Native adapters are not fully tested — use at your own risk.</strong>{" "}
            Login and account reads are verified for{" "}
            {connectableNativeLabel || "the currently selectable native brokers"}, but native order
            placement (place / modify / cancel) has{" "}
            <strong className="text-text-primary">not been live-verified for any broker</strong> yet —
            OpenAlgo is the recommended, community-tested path.{" "}
            {unavailableNativeLabel
              ? `${unavailableNativeLabel} ${unavailableNativeVerb} visible as catalogued adapters and remain disabled until their live checks pass.`
              : "Unavailable adapters stay disabled until their live checks pass."}
          </p>
          {unavailableNativeBlockers.length > 0 && (
            <ul className="space-y-1 text-xs text-text-muted" data-testid="native-connect-blockers">
              {unavailableNativeBlockers.map((b) => (
                <li key={b.adapter_id}>
                  <span className="font-medium text-text-secondary">{b.display_name}:</span>{" "}
                  {blockerLabel(b.native_connect_blockers)}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {mcpBrokers.length > 0 && (
        <div className="space-y-3" aria-label="Broker MCP assistants">
          <div className="flex items-center gap-2">
            <Bot className="size-4 text-accent" aria-hidden="true" />
            <h3 className="text-sm font-medium text-text-secondary">Broker MCP assistants</h3>
          </div>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(14rem,1fr))] gap-3">
            {mcpBrokers.map((entry) => {
              const loginSteps = entry.mcp.login_steps;
              const cautions = entry.mcp.cautions;
              const clientConfigs = entry.mcp.client_configs.filter((config) => (
                config.url || mcpCommand(config) || mcpConfigJson(config)
              ));
              return (
                <article
                  key={entry.adapter_id}
                  className="rounded-lg border border-border-default bg-surface-card/60 p-3"
                  data-testid={`broker-mcp-${entry.adapter_id}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="text-sm font-medium text-text-primary">{entry.display_name}</div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        <Badge variant="outline" className="text-xxs">
                          {entry.mcp.read_only ? "Read-only" : "MCP trade tools"}
                        </Badge>
                        {!entry.connectable && (
                          <Badge variant="outline" className="text-xxs">Native unavailable</Badge>
                        )}
                        {entry.requires_static_ip && (
                          <Badge variant="outline" className="border-warning/50 text-xxs text-warning">
                            Static IP for live API orders
                          </Badge>
                        )}
                      </div>
                    </div>
                    <a
                      href={entry.mcp.docs_url}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={`${entry.display_name} MCP docs`}
                      className="inline-flex size-8 items-center justify-center rounded-md text-text-muted hover:bg-surface-hover hover:text-text-primary"
                    >
                      <ExternalLink className="size-4" aria-hidden="true" />
                    </a>
                  </div>

                  <p className="mt-2 text-xs text-text-muted">{entry.mcp.auth_mode}</p>
                  <p className="mt-1 text-xxs text-text-muted">{entry.mcp.reauth}</p>
                  {!entry.connectable && entry.native_connect_blockers.length > 0 && (
                    <p className="mt-2 text-xxs text-warning">
                      Native blockers: {blockerLabel(entry.native_connect_blockers)}
                    </p>
                  )}

                  {loginSteps.length > 0 && (
                    <div className="mt-3 space-y-1">
                      <div className="text-xs font-medium text-text-secondary">MCP login</div>
                      <ol className="list-decimal space-y-1 pl-4 text-xxs text-text-muted">
                        {loginSteps.map((step, index) => (
                          <li key={`${entry.adapter_id}-mcp-login-${index}`} className="break-words">
                            {step}
                          </li>
                        ))}
                      </ol>
                    </div>
                  )}

                  <div className="mt-3 grid grid-cols-[1fr_auto] items-end gap-2">
                    <div>
                      <Label className="text-xs text-text-secondary mb-1.5 block">MCP URL</Label>
                      <code
                        aria-label={`${entry.display_name} MCP URL value`}
                        className="block min-h-9 rounded-md border border-border-default bg-surface-elevated px-3 py-2 font-mono text-xs text-text-primary break-all"
                      >
                        {entry.mcp.remote_url}
                      </code>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={`Copy ${entry.display_name} MCP URL`}
                      onClick={() => {
                        void copySetupUrl(`${entry.display_name} MCP URL`, entry.mcp.remote_url);
                      }}
                    >
                      <Copy className="size-4" aria-hidden="true" />
                    </Button>
                  </div>

                  {clientConfigs.length > 0 && (
                    <div className="mt-3 space-y-2">
                      <div className="text-xs font-medium text-text-secondary">Client setup</div>
                      {clientConfigs.map((config) => {
                        const command = mcpCommand(config);
                        const configJson = mcpConfigJson(config);
                        return (
                          <div
                            key={`${entry.adapter_id}-${config.id}`}
                            className="space-y-2 border-t border-border-subtle pt-2"
                            data-testid={`broker-mcp-${entry.adapter_id}-${config.id}`}
                          >
                            <div className="break-words text-xs font-medium text-text-primary">
                              {config.label}
                            </div>
                            {config.url && (
                              <McpSetupValue
                                label="URL"
                                copyLabel={`${entry.display_name} ${config.label} URL`}
                                value={config.url}
                                onCopy={copySetupUrl}
                              />
                            )}
                            {command && (
                              <McpSetupValue
                                label="Command"
                                copyLabel={`${entry.display_name} ${config.label} command`}
                                value={command}
                                onCopy={copySetupUrl}
                              />
                            )}
                            {configJson && (
                              <McpSetupValue
                                label="JSON config"
                                copyLabel={`${entry.display_name} ${config.label} JSON config`}
                                value={configJson}
                                multiline
                                onCopy={copySetupUrl}
                              />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {entry.mcp.use_cases.length > 0 && (
                    <div className="mt-3 space-y-1.5">
                      <div className="text-xs font-medium text-text-secondary">Use cases</div>
                      <ul className="space-y-1 text-xxs text-text-muted">
                        {entry.mcp.use_cases.map((useCase, index) => (
                          <li
                            key={`${entry.adapter_id}-mcp-use-case-${index}`}
                            className="break-words leading-snug"
                          >
                            {useCase}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {cautions.length > 0 && (
                    <ul className="mt-2 space-y-1 text-xxs text-warning">
                      {cautions.map((caution, index) => (
                        <li key={`${entry.adapter_id}-mcp-caution-${index}`} className="break-words">
                          {caution}
                        </li>
                      ))}
                    </ul>
                  )}
                </article>
              );
            })}
          </div>
        </div>
      )}

      {/* Connected accounts */}
      <div className="space-y-2">
        <h3 className="text-sm font-medium text-text-secondary">Connected accounts</h3>
        {accounts.length === 0 ? (
          <p className="text-sm text-text-muted">No broker accounts connected yet.</p>
        ) : (
          <ul className="space-y-2">
            {accounts.map((a) => {
              const connected = a.status === "connected";
              const needsFreshLogin = a.status === "token_expired" || !!a.needs_relogin;
              const retryLater = !!a.login_retryable;
              const canSetPrimary = canPromotePrimaryAccount(a);
              return (
              <li
                key={brokerAccountKey(a)}
                className="flex items-center justify-between rounded-lg border border-border-default bg-surface-card p-3"
              >
                <div className="flex items-center gap-3">
                  {connected ? (
                    <CheckCircle2 className="size-4 text-profit" aria-hidden="true" />
                  ) : needsFreshLogin || retryLater ? (
                    <AlertTriangle className="size-4 text-warning" aria-hidden="true" />
                  ) : (
                    <XCircle className="size-4 text-loss" aria-hidden="true" />
                  )}
                  <div>
                    <div className="text-sm text-text-primary font-medium">
                      {a.label || a.broker} · {a.account_id}
                    </div>
                    <div className="text-xs text-text-muted">
                      {a.broker}
                      {a.is_primary ? " · primary" : ""}
                      {a.read_only ? " · read-only" : ""}
                      {connected
                        ? ` · connected${a.expires_at ? ` · ${expiryLabel(a.expires_at)}` : ""}`
                        : needsFreshLogin
                          ? " · needs fresh login"
                          : retryLater
                            ? " · retry later"
                          : " · no live session"}
                    </div>
                    {!connected && (needsFreshLogin || retryLater) && a.error_message && (
                      <div className="text-xxs text-warning mt-0.5">{a.error_message}</div>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  {canSetPrimary && (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Set ${a.broker} ${a.account_id} as primary`}
                      onClick={() => setPrimaryMutation.mutate({ adapter: a.broker, account: a.account_id })}
                      disabled={setPrimaryMutation.isPending}
                    >
                      <Star className="size-4" aria-hidden="true" />
                    </Button>
                  )}
                  {!connected && (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Re-authenticate ${a.broker} ${a.account_id}`}
                      onClick={() => reloginMutation.mutate({ adapter: a.broker, account: a.account_id })}
                      disabled={reloginMutation.isPending}
                    >
                      <RefreshCw
                        className={`size-4 ${reloginMutation.isPending ? "animate-spin" : ""}`}
                        aria-hidden="true"
                      />
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Disconnect ${a.broker} ${a.account_id}`}
                    onClick={() => removeMutation.mutate({ adapter: a.broker, account: a.account_id })}
                    disabled={removeMutation.isPending}
                  >
                    <Trash2 className="size-4" aria-hidden="true" />
                  </Button>
                </div>
              </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Legacy gateway accounts — only shown when any exist. */}
      {gatewayAccounts.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-text-secondary">Gateway accounts</h3>
          <p className="text-xs text-text-muted">
            Broker accounts connected through the FlintTrade gateway (OpenAlgo bridge / catalogue path).
          </p>
          <ul className="space-y-2">
            {gatewayAccounts.map((a: BrokerAccount) => (
              <li
                key={`gateway:${a.broker}:${a.account_id}`}
                className="flex items-center justify-between rounded-lg border border-border-default bg-surface-card p-3"
              >
                <div className="flex items-center gap-3">
                  {a.is_primary && (
                    <Star className="size-4 shrink-0 fill-accent text-accent" aria-label="Primary account" />
                  )}
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-text-primary truncate">
                      {a.label || a.account_id}
                    </div>
                    <div className="text-xs text-text-muted capitalize">
                      {a.broker}
                      {a.is_primary ? " · primary" : ""}
                      {a.read_only ? " · read-only" : ""}
                    </div>
                    {a.error_message && (
                      <div className="text-xxs text-warning mt-0.5 truncate" title={a.error_message}>
                        {a.error_message}
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Badge variant="outline" className="text-xxs capitalize">{a.status}</Badge>
                  {canPromotePrimaryAccount(a) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Set ${a.label || a.account_id} as primary`}
                      title="Set as primary"
                      onClick={() => gatewaySetPrimaryMutation.mutate({ accountId: a.account_id, broker: a.broker })}
                      disabled={gatewayBusy}
                    >
                      <Star className="size-4" aria-hidden="true" />
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Reconnect ${a.label || a.account_id}`}
                    title="Reconnect"
                    onClick={() => gatewayReconnectMutation.mutate({ accountId: a.account_id, broker: a.broker })}
                    disabled={gatewayBusy}
                  >
                    <RefreshCw className="size-4" aria-hidden="true" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Disconnect ${a.label || a.account_id}`}
                    title="Remove account"
                    onClick={() => gatewayRemoveMutation.mutate({ accountId: a.account_id, broker: a.broker })}
                    disabled={gatewayBusy}
                  >
                    <Trash2 className="size-4 text-loss" aria-hidden="true" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Connect a new account */}
      <div className="space-y-4 rounded-lg border border-border-default bg-surface-card/60 p-4">
        <h3 className="text-sm font-medium text-text-secondary">Connect a broker</h3>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <Label htmlFor="broker-select" className="text-xs text-text-secondary mb-1.5 block">Broker</Label>
            <Select
              value={selectedBroker}
              onValueChange={(v) => {
                setSelectedBroker(v);
                const first = brokers.find((b) => b.adapter_id === v)?.auth_methods[0]?.id ?? "";
                setSelectedMethodId(first);
                resetForm();
              }}
            >
              <SelectTrigger id="broker-select"><SelectValue placeholder="Select a broker" /></SelectTrigger>
              <SelectContent>
                {brokers.map((b) => (
                  <SelectItem key={b.adapter_id} value={b.adapter_id} disabled={!b.connectable}>
                    <span>{b.display_name}</span>
                    {!b.connectable && <span className="text-xs text-text-muted"> · Coming soon</span>}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {broker && brokerConnectable && (
            <div>
              <Label htmlFor="method-select" className="text-xs text-text-secondary mb-1.5 block">Login method</Label>
              <Select value={selectedMethodId} onValueChange={(v) => { setSelectedMethodId(v); setFields({}); setError(""); }}>
                <SelectTrigger id="method-select"><SelectValue placeholder="Select a method" /></SelectTrigger>
                <SelectContent>
                  {broker.auth_methods.map((m) => (
                    <SelectItem key={m.id} value={m.id}>{m.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>

        {broker && !brokerConnectable && (
          <div role="status" className="flex items-center gap-2 text-sm text-warning">
            <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
            {broker.display_name} native connect is coming soon.
          </div>
        )}

        {broker && (
          <div
            className="flex flex-wrap items-center gap-2 text-xs text-text-muted"
            data-testid="native-broker-sdk-status"
          >
            <span>SDK readiness</span>
            <Badge
              variant="outline"
              className={`text-xs ${sdkStatusTone(broker.sdk_attestation?.status)}`}
            >
              {sdkStatusLabel(broker)}
            </Badge>
            {!brokerSdkReady && (
              <span className="text-loss">Run setup or sync dependencies before connecting.</span>
            )}
          </div>
        )}

        {broker?.requires_static_ip && (
          <div
            role="status"
            className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-text-secondary"
            data-testid="native-broker-static-ip"
          >
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
            <span>
              <strong className="text-text-primary">Static outbound IP required</strong> for live API orders.
            </span>
          </div>
        )}

        {method && brokerConnectable && (
          <div className="space-y-3">
            <p className="text-xs text-text-muted">{method.description}</p>
            {method.kind === "oauth" && <Badge variant="outline" className="text-xs">Opens {broker?.display_name} in a new tab</Badge>}

            {method.kind === "oauth" && (
              <div className="space-y-2">
                {[
                  {
                    label: "Redirect URL",
                    value: oauthRedirectUri,
                    help: "Required for OAuth approval callbacks.",
                  },
                  {
                    label: "Postback URL (optional)",
                    value: brokerPostbackUri,
                    help: "Use only with a broker-reachable public or tunnel URL. Localhost is for FlintTrade diagnostics.",
                  },
                ].map(({ label, value, help }) => (
                  <div key={label} className="grid grid-cols-[1fr_auto] items-end gap-2">
                    <div>
                      <Label className="text-xs text-text-secondary mb-1.5 block">{label}</Label>
                      <Input readOnly value={value} className="font-mono text-xs" />
                      <p className="text-xxs text-text-muted mt-1">{help}</p>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={`Copy ${label.toLowerCase()}`}
                      onClick={() => {
                        void copySetupUrl(label, value);
                      }}
                    >
                      <Copy className="size-4" aria-hidden="true" />
                    </Button>
                  </div>
                ))}
              </div>
            )}

            <div>
              <Label htmlFor="account-id" className="text-xs text-text-secondary mb-1.5 block">Account ID / client code</Label>
              <Input
                id="account-id"
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
                placeholder="e.g. your client code"
              />
            </div>

            <div>
              <Label htmlFor="account-label" className="text-xs text-text-secondary mb-1.5 block">
                Account label <span className="text-text-muted">(optional)</span>
              </Label>
              <Input
                id="account-label"
                value={accountLabel}
                onChange={(e) => setAccountLabel(e.target.value)}
                placeholder={broker ? `${broker.display_name} main` : "e.g. primary trading account"}
              />
            </div>

            {method.fields.map((f) => (
              <div key={f.name}>
                <Label htmlFor={`field-${f.name}`} className="text-xs text-text-secondary mb-1.5 block">
                  {f.label}{!f.required && <span className="text-text-muted"> (optional)</span>}
                </Label>
                <Input
                  id={`field-${f.name}`}
                  type={f.secret ? "password" : "text"}
                  autoComplete={f.secret ? "off" : undefined}
                  value={fields[f.name] ?? ""}
                  onChange={(e) => setFields((prev) => ({ ...prev, [f.name]: e.target.value }))}
                />
                {f.help && <p className="text-xxs text-text-muted mt-1">{f.help}</p>}
              </div>
            ))}

            <Button
              onClick={() => connectMutation.mutate()}
              disabled={connectMutation.isPending || !brokerConnectable || !brokerSdkReady}
              className="w-full sm:w-auto"
            >
              {connectMutation.isPending && <Loader2 className="size-4 mr-2 animate-spin" aria-hidden="true" />}
              {method.kind === "oauth" ? `Log in with ${broker?.display_name}` : "Connect"}
            </Button>
          </div>
        )}

        {/* Shared feedback — visible for connect AND re-authenticate actions,
            so a relogin result shows even before a broker is picked. */}
        {error && (
          <div role="alert" className="text-sm text-loss flex items-center gap-2">
            <XCircle className="size-4 shrink-0" aria-hidden="true" />{error}
          </div>
        )}
        {notice && (
          <div role="status" className="text-sm text-profit flex items-center gap-2">
            {method?.kind === "oauth" ? <ExternalLink className="size-4 shrink-0" aria-hidden="true" /> : <CheckCircle2 className="size-4 shrink-0" aria-hidden="true" />}
            {notice}
          </div>
        )}
      </div>
    </div>
  );
}
