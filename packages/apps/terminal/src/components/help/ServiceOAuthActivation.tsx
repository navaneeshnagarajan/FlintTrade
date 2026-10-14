import { useRef, useState, useLayoutEffect } from "react";
import { Button } from "@/components/ui/button";
import { captureAuthSessionFence, isAuthSessionFenceCurrent, useAuthStore } from "@/stores/authStore";
import { configureProviderOAuth } from "@/services/serviceOAuth";
import type { ServiceConnectionCollection } from "@/services/serviceConnectionControls";

interface Props {
  snapshot: ServiceConnectionCollection;
  disabled: boolean;
  onChanged: (value: ServiceConnectionCollection) => void;
  onBlocked?: (blocked: boolean) => void;
}
export default function ServiceOAuthActivation(props: Props) {
  const generation = useAuthStore(state => state.sessionGeneration);
  return <Activation key={`${generation}:${props.snapshot.etag}`} {...props} />;
}
function Activation({ snapshot, disabled, onChanged, onBlocked }: Props) {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const inFlight = useRef(false);
  useLayoutEffect(() => { generation.current++; return () => { generation.current++; }; }, []);
  async function save() {
    if (disabled || inFlight.current) return;
    const fence = captureAuthSessionFence(), epoch = generation.current;
    const current = () => isAuthSessionFenceCurrent(fence) && generation.current === epoch;
    inFlight.current = true; setBusy(true); onBlocked?.(true);
    try {
      const read = await configureProviderOAuth(snapshot, snapshot.oauth?.configured ? "api_only" : "local_oss");
      if (!current()) return;
      setConfirm(false); onBlocked?.(false); onChanged(read);
      setNotice(read.oauth?.configured ? "Local/OSS activation read back. Sign-in is separate; no provider was contacted." : "API-only setting read back. Existing remote sessions were not revoked.");
    } catch {
      if (current()) setNotice("Activation outcome unavailable. Refresh and review; no request was retried.");
    } finally { if (current()) { setBusy(false); inFlight.current = false; } }
  }
  return <section aria-label="Installed provider sign-in activation" className="space-y-2">
    <p className="text-xs">API keys are the default. Only enable provider sign-in for this local/OSS installation. Hosted, commercial and partner deployments, xAI and Anthropic OAuth are unsupported. Create a connection first. The explicit setting survives restart; the desktop binds the callback to its actual port.</p>
    <Button size="sm" variant="outline" disabled={disabled || busy} onClick={() => setConfirm(true)}>{snapshot.oauth?.configured ? "Use API-only mode" : "Enable local/OSS provider sign-in"}</Button>
    {confirm && <div className="space-y-2"><p className="text-xs">This changes acquisition availability for this installation, not task permissions or provider entitlement. It cancels pending sign-in attempts, but does not revoke existing remote credentials.</p><Button size="sm" disabled={disabled || busy} onClick={() => void save()}>{snapshot.oauth?.configured ? "Confirm API-only mode" : "Confirm local/OSS activation"}</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => setConfirm(false)}>Cancel activation</Button></div>}
    {notice && <p role="status" className="text-xs">{notice}</p>}
  </section>;
}
