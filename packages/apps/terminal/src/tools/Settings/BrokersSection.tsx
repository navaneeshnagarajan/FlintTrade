/**
 * BrokersSection — connect native broker accounts (Phase 1 G4 UI).
 *
 * Lets the operator connect Dhan / Upstox / Kotak Neo / IndMoney using their
 * preferred login method (access token, PIN+TOTP, OAuth, TOTP+MPIN). The method
 * catalogue + form fields come from the backend (`/native/brokers`), so the UI
 * stays in lockstep with what each adapter supports. Credentials are POSTed to
 * the local backend only. OAuth opens the broker's approval page in a new tab;
 * the backend's loopback callback establishes the session.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, XCircle, Loader2, Trash2, ExternalLink } from "lucide-react";
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
import {
  listNativeBrokers,
  listNativeAccounts,
  connectNativeAccount,
  oauthStartNativeAccount,
  removeNativeAccount,
  type NativeAuthMethod,
} from "@/services/ftApi.native";

const BROKERS_KEY = ["native", "brokers"] as const;
const ACCOUNTS_KEY = ["native", "accounts"] as const;

function expiryLabel(expiresAt?: number | null): string {
  if (!expiresAt) return "";
  const ms = expiresAt * 1000 - Date.now();
  if (ms <= 0) return "expired";
  const hours = Math.floor(ms / 3_600_000);
  const mins = Math.floor((ms % 3_600_000) / 60_000);
  return hours > 0 ? `expires in ${hours}h ${mins}m` : `expires in ${mins}m`;
}

export function BrokersSection() {
  const qc = useQueryClient();
  const brokersQuery = useQuery({ queryKey: BROKERS_KEY, queryFn: listNativeBrokers });
  const accountsQuery = useQuery({ queryKey: ACCOUNTS_KEY, queryFn: listNativeAccounts });

  const brokers = brokersQuery.data ?? [];
  const [selectedBroker, setSelectedBroker] = useState<string>("");
  const [selectedMethodId, setSelectedMethodId] = useState<string>("");
  const [accountId, setAccountId] = useState<string>("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState<string>("");
  const [notice, setNotice] = useState<string>("");

  const broker = brokers.find((b) => b.adapter_id === selectedBroker);
  const method: NativeAuthMethod | undefined = broker?.auth_methods.find((m) => m.id === selectedMethodId);

  function resetForm() {
    setFields({});
    setAccountId("");
    setError("");
    setNotice("");
  }

  const connectMutation = useMutation({
    mutationFn: async () => {
      if (!broker || !method) throw new Error("Pick a broker and a login method.");
      if (!accountId.trim()) throw new Error("Enter an account ID / client code.");
      for (const f of method.fields) {
        if (f.required && !fields[f.name]?.trim()) throw new Error(`${f.label} is required.`);
      }
      if (method.kind === "oauth") {
        const started = await oauthStartNativeAccount({
          adapter_id: broker.adapter_id,
          account_id: accountId.trim(),
          api_key: fields.api_key ?? "",
          api_secret: fields.api_secret ?? "",
        });
        window.open(started.auth_url, "_blank", "noopener");
        return {
          oauth: true,
          message: `Approve access in the new tab. Ensure your ${broker.display_name} app's redirect URL is set to ${started.redirect_uri}.`,
        };
      }
      const result = await connectNativeAccount({
        adapter_id: broker.adapter_id,
        account_id: accountId.trim(),
        credentials: Object.fromEntries(method.fields.map((f) => [f.name, fields[f.name] ?? ""])),
      });
      if (!result.connected) throw new Error(result.message || "Login did not establish a session.");
      return { oauth: false, message: `${broker.display_name} account ${accountId.trim()} connected.` };
    },
    onSuccess: (r) => {
      setError("");
      setNotice(r.message);
      if (!r.oauth) resetForm();
      // OAuth completes out-of-band in the callback tab; refresh accounts shortly after.
      setTimeout(() => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }), r.oauth ? 4000 : 0);
      qc.invalidateQueries({ queryKey: ACCOUNTS_KEY });
    },
    onError: (e: unknown) => {
      setNotice("");
      setError(e instanceof Error ? e.message : "Connection failed.");
    },
  });

  const removeMutation = useMutation({
    mutationFn: (sel: { adapter: string; account: string }) => removeNativeAccount(sel.adapter, sel.account),
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-heading font-semibold text-base text-text-primary mb-1">Brokers</h2>
        <p className="text-sm text-text-muted">
          Connect your broker accounts. Pick the login method you prefer for each broker — credentials
          go only to your local FlintTrade backend.
        </p>
      </div>

      {/* Connected accounts */}
      <div className="space-y-2">
        <h3 className="text-sm font-medium text-text-secondary">Connected accounts</h3>
        {(accountsQuery.data ?? []).length === 0 ? (
          <p className="text-sm text-text-muted">No broker accounts connected yet.</p>
        ) : (
          <ul className="space-y-2">
            {(accountsQuery.data ?? []).map((a) => (
              <li
                key={`${a.adapter_id}:${a.account_id}`}
                className="flex items-center justify-between rounded-lg border border-border-default bg-surface-card p-3"
              >
                <div className="flex items-center gap-3">
                  {a.has_session ? (
                    <CheckCircle2 className="size-4 text-profit" aria-hidden="true" />
                  ) : (
                    <XCircle className="size-4 text-loss" aria-hidden="true" />
                  )}
                  <div>
                    <div className="text-sm text-text-primary font-medium">
                      {a.label || a.adapter_id} · {a.account_id}
                    </div>
                    <div className="text-xs text-text-muted">
                      {a.adapter_id}
                      {a.is_primary ? " · primary" : ""}
                      {a.has_session ? ` · connected${a.expires_at ? ` · ${expiryLabel(a.expires_at)}` : ""}` : " · no live session"}
                    </div>
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={`Disconnect ${a.adapter_id} ${a.account_id}`}
                  onClick={() => removeMutation.mutate({ adapter: a.adapter_id, account: a.account_id })}
                  disabled={removeMutation.isPending}
                >
                  <Trash2 className="size-4" aria-hidden="true" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>

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
                  <SelectItem key={b.adapter_id} value={b.adapter_id}>{b.display_name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {broker && (
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

        {method && (
          <div className="space-y-3">
            <p className="text-xs text-text-muted">{method.description}</p>
            {method.kind === "oauth" && <Badge variant="outline" className="text-xs">Opens {broker?.display_name} in a new tab</Badge>}

            <div>
              <Label htmlFor="account-id" className="text-xs text-text-secondary mb-1.5 block">Account ID / client code</Label>
              <Input
                id="account-id"
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
                placeholder="e.g. your client code"
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

            {error && (
              <div role="alert" className="text-sm text-loss flex items-center gap-2">
                <XCircle className="size-4 shrink-0" aria-hidden="true" />{error}
              </div>
            )}
            {notice && (
              <div role="status" className="text-sm text-profit flex items-center gap-2">
                {method.kind === "oauth" ? <ExternalLink className="size-4 shrink-0" aria-hidden="true" /> : <CheckCircle2 className="size-4 shrink-0" aria-hidden="true" />}
                {notice}
              </div>
            )}

            <Button onClick={() => connectMutation.mutate()} disabled={connectMutation.isPending} className="w-full sm:w-auto">
              {connectMutation.isPending && <Loader2 className="size-4 mr-2 animate-spin" aria-hidden="true" />}
              {method.kind === "oauth" ? `Log in with ${broker?.display_name}` : "Connect"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
