import { useCallback, useRef, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import ServiceOAuthControls from "./ServiceOAuthControls";
import ServiceOAuthActivation from "./ServiceOAuthActivation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConnectionControlError, connectionProfiles, createConnection, deleteConnection, isOperatorEndpoint, updateConnection, type ConnectionChanges, type ServiceConnection, type ServiceConnectionCollection } from "@/services/serviceConnectionControls";
import { captureAuthSessionFence, isAuthSessionFenceCurrent } from "@/stores/authStore";

interface Props { snapshot?: ServiceConnectionCollection; unavailable: boolean; blocked?: boolean; onChanged: (snapshot: ServiceConnectionCollection) => void; onRefresh: () => Promise<unknown>; onBlocked?: (blocked: boolean) => void }
const selectClass = "block w-full rounded border border-border-default bg-surface-card p-2";
export default function ServiceConnectionSetup({ snapshot, unavailable, blocked = false, onChanged, onRefresh, onBlocked }: Props) {
  const [open, setOpen] = useState(false);
  const [provider, setProvider] = useState("");
  const [label, setLabel] = useState("");
  const [model, setModel] = useState("");
  const [auth, setAuth] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [editing, setEditing] = useState<ServiceConnection | null>(null);
  const [editSnapshot, setEditSnapshot] = useState<ServiceConnectionCollection>();
  const [credentialAction, setCredentialAction] = useState("retain");
  const [confirm, setConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const credential = useRef<HTMLInputElement>(null);
  const credentialRef = useCallback((node: HTMLInputElement | null) => {
    if (credential.current && credential.current !== node) credential.current.value = "";
    credential.current = node;
  }, []);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const profile = connectionProfiles.find(item => item.id === provider);
  const locked = unavailable || busy || needsRefresh || blocked;
  async function refresh() {
    const fence = captureAuthSessionFence();
    if (credential.current) credential.current.value = "";
    setOpen(false); setConfirm(false); setBusy(true); onBlocked?.(true);
    try {
      await onRefresh();
      if (isAuthSessionFenceCurrent(fence)) { setNeedsRefresh(false); setError(""); onBlocked?.(false); setNotice("Collection refreshed. Review current configuration before submitting a new action; no previous mutation was retried. An uncertain earlier outcome remains uncertain; inspect the inventory, especially before creating another connection."); }
    } catch {
      if (isAuthSessionFenceCurrent(fence)) { setNeedsRefresh(true); setError("Collection refresh failed. Changes remain blocked."); }
    } finally { if (isAuthSessionFenceCurrent(fence)) setBusy(false); }
  }
  function openEditor(row: ServiceConnection | null) {
    if (locked) return;
    if (credential.current) credential.current.value = "";
    setOpen(true); setEditing(row); setEditSnapshot(snapshot); setConfirm(false); setDeleting(false); setCredentialAction("retain");
    setProvider(row?.provider_id ?? ""); setLabel(row?.label ?? ""); setModel(row?.model ?? ""); setAuth(row?.auth_mode ?? "");
    setEndpoint(row?.endpoint ?? "");
  }
  async function save() {
    if (!editSnapshot || locked) return;
    if (!deleting && credentialAction === "replace" && !credential.current?.value) {
      setError("Enter a credential or choose not to bind one. No request was sent."); return;
    }
    const fence = captureAuthSessionFence();
    setBusy(true); setError(""); setNotice(""); onBlocked?.(true);
    const changes: ConnectionChanges = { label, model, auth_mode: profile?.auth.length ? auth : null, ...(profile?.operatorEndpoint ? { endpoint } : {}), ...(credentialAction === "replace" ? { credential: credential.current?.value ?? "" } : {}), ...(credentialAction === "clear" ? { clear_credential: true } : {}) };
    if (credential.current) credential.current.value = "";
    try {
      const result = deleting && editing ? await deleteConnection(editSnapshot, editing, crypto.randomUUID()) : editing
        ? await updateConnection(editSnapshot, editing, changes, crypto.randomUUID())
        : await createConnection(editSnapshot, { provider_id: provider, ...changes }, crypto.randomUUID());
      if (!isAuthSessionFenceCurrent(fence)) return;
      onChanged(result); setOpen(false); onBlocked?.(false);
      setNotice(deleting ? "Local configuration deleted and absence verified. Remote credentials and accepted work were not revoked." : "Configuration saved and read back. No provider login or qualification was performed.");
    } catch (error) {
      if (isAuthSessionFenceCurrent(fence)) {
        setOpen(false); setConfirm(false); setNeedsRefresh(true);
        setError(error instanceof ConnectionControlError ? error.message : "Connection change could not be verified. Refresh and review before explicitly submitting again.");
      }
    } finally { if (isAuthSessionFenceCurrent(fence)) setBusy(false); }
  }
  return <section aria-label="Service connection setup" className="space-y-3 rounded border border-border-default p-3">
    <h3 className="font-semibold">Service connection setup</h3>
    <p className="text-xs text-text-muted">Configure destination-bound credentials in the existing encrypted core owner. No entitlement, budget, privacy grant, evaluation evidence or admission policy is created here. Do not put secrets in labels, model names or URLs.</p>
    <Button size="sm" variant="outline" disabled={busy} onClick={() => void refresh()}>Refresh connections</Button>
    {snapshot?.oauth?.desktop_activation && <ServiceOAuthActivation snapshot={snapshot} disabled={locked || !snapshot.connections.length} onChanged={onChanged} onBlocked={onBlocked} />}
    {blocked && !busy && <p className="text-xs text-warning">A previous connection change is pending or unverified. Refresh the inventory and review it before any new action. No previous request will be retried.</p>}
    {snapshot?.connections.map(row => <div key={row.connection_id} className="space-y-1 rounded border border-border-default p-2">
      <p className="break-all text-sm">{row.label} · {row.provider_id} · {row.model || "No model selected"}</p>
      <p className="break-all text-xs text-text-muted">{row.connection_id} · {row.endpoint ?? "Managed runtime"} · {row.auth_mode ?? "No authentication"}</p>
      <p className="text-xs">Credential: {row.credential_configured ? "stored, not verified" : "not stored"}. Authentication, reachability and qualification are not established.</p>
      <ServiceOAuthControls snapshot={snapshot} row={row} disabled={locked} onChanged={onChanged} onBlocked={onBlocked} />
      <Button size="sm" variant="outline" aria-label={`Edit ${row.label}`} disabled={locked} onClick={() => openEditor(row)}><Pencil aria-hidden="true" />Edit</Button>
      <Button size="sm" variant="outline" aria-label={`Delete ${row.label}`} disabled={locked} onClick={() => { openEditor(row); setDeleting(true); setConfirm(true); }}><Trash2 aria-hidden="true" />Delete</Button>
    </div>)}
    <Button size="sm" variant="outline" disabled={locked || !snapshot} onClick={() => openEditor(null)}><Plus aria-hidden="true" />Add service connection</Button>
    {open && <div className="space-y-3">
      <fieldset disabled={busy || confirm} className="grid gap-3 sm:grid-cols-2">
        <label className="text-xs">Provider<select aria-label="Connection provider" disabled={!!editing} className={selectClass} value={provider} onChange={event => { setProvider(event.target.value); setAuth(""); setModel(""); setEndpoint(""); setCredentialAction("retain"); if (credential.current) credential.current.value = ""; }}><option value="">Choose an exact provider</option>{connectionProfiles.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="text-xs">Label<Input aria-label="Connection label" value={label} maxLength={128} onChange={event => setLabel(event.target.value)} /></label>
        <label className="text-xs">Exact model (blank = unset, no default)<Input aria-label="Connection model" value={model} maxLength={256} onChange={event => setModel(event.target.value)} /></label>
        <label className="text-xs">Authentication<select aria-label="Connection authentication" disabled={!profile?.auth.length} className={selectClass} value={auth} onChange={event => { setAuth(event.target.value); if (credential.current) credential.current.value = ""; setCredentialAction("retain"); }}><option value="">{profile && !profile.auth.length ? "No authentication supported by this profile" : "Choose authentication"}</option>{profile?.auth.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
        {profile?.operatorEndpoint && <label className="text-xs">Operator base URL (no credentials, query or fragment)<Input aria-label="Connection endpoint" value={endpoint} maxLength={2048} onChange={event => { setEndpoint(event.target.value); if (credential.current) credential.current.value = ""; setCredentialAction("retain"); }} /></label>}
        <label className="text-xs">Credential action<select aria-label="Credential action" disabled={!profile?.auth.length || !auth} className={selectClass} value={credentialAction} onChange={event => { setCredentialAction(event.target.value); if (credential.current) credential.current.value = ""; }}><option value="retain">{editing ? "Keep binding unless destination/auth changes" : "Do not bind a credential"}</option><option value="replace">{editing ? "Replace stored credential" : "Bind a credential"}</option>{editing && <option value="clear">Clear local credential binding</option>}</select></label>
        {credentialAction === "replace" && <label className="text-xs">Credential (transient input only)<Input ref={credentialRef} aria-label="Connection credential" type="password" autoComplete="off" spellCheck={false} /></label>}
      </fieldset>
      {profile && <p className="break-all text-xs">Stored endpoint: {profile.operatorEndpoint ? endpoint || "Explicit base URL required" : profile.endpoint ?? "None (managed runtime)"}. Separate admission protocols and roles: {profile.protocols} Saving does not select or enable any protocol or role.</p>}
      <p className="text-xs text-warning">OAuth acquisition/PKCE is not implemented for unsupported providers and is unavailable unless this backend declares a configured route. Provider sign-in is available only for explicitly configured local/OSS ChatGPT and OpenRouter routes after creating the exact connection. Other routes refuse unsupported OAuth; API keys remain separate. Manual binding is not a successful login. Do not extract another application's subscription credentials. xAI OAuth entitlement remains unresolved; only api_key is declared. Subscription caps differ from ordinary API access.</p>
      {!snapshot?.oauth && <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled>Sign in with provider (unavailable)</Button><Button size="sm" variant="outline" disabled>Refresh provider token (unavailable)</Button><Button size="sm" variant="outline" disabled>Revoke remote credential (unavailable)</Button></div>}
      {!confirm && <Button size="sm" disabled={locked || !profile || !label.trim() || (profile.auth.length > 0 && !auth) || (profile.operatorEndpoint && !isOperatorEndpoint(endpoint))} onClick={() => editing ? setConfirm(true) : void save()}>{editing ? "Review connection update" : "Create configuration"}</Button>}
      {confirm && editing && <section aria-label="Confirm connection change" className="space-y-2 rounded border border-warning p-3">
        <h4 className="font-semibold">Confirm exact scope and impact</h4>
        <p className="break-all text-xs">{editing.connection_id} · {provider}. Endpoint: {editing.endpoint ?? "None"} → {profile?.operatorEndpoint ? endpoint : profile?.endpoint ?? "None"}. Label: {editing.label} → {label}. Model: {editing.model || "Unset"} → {model || "Unset"}. Authentication: {editing.auth_mode ?? "None"} → {auth || "None"}. Credential action: {credentialAction}.</p>
        <p className="text-xs text-warning">Changing destination or authentication clears the old local binding unless you explicitly bind new material for that destination.</p>
        <p className="text-xs text-warning">This changes local configuration and invalidates revision-bound admission/routing selections. Replacing a local binding does not revoke the remote credential or cancel accepted work. Reconfigure explicit admission before use.</p>
        {deleting && <p className="text-sm text-loss">Delete this exact local connection and its credential binding. Remote revocation is not performed by deleting configuration; use provider disconnect first when supported.</p>}
        <Button size="sm" disabled={busy || unavailable} onClick={() => void save()}>{deleting ? "Confirm delete" : "Confirm update"}</Button>
      </section>}
      <Button size="sm" variant="outline" disabled={busy} onClick={() => { if (credential.current) credential.current.value = ""; setOpen(false); setConfirm(false); }}>Cancel setup</Button>
    </div>}
    {notice && <p role="status" className="text-sm">{notice}</p>}
    {error && <p role="alert" className="text-sm text-warning">{error}</p>}
  </section>;
}
