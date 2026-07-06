/**
 * LoginRoute — daily login screen (password + TOTP or PIN).
 *
 * Rendered inside /welcome flow for returning users.
 * Not a standalone route — it's a component used by WelcomeRoute.
 *
 * The 2FA field accepts EITHER a 6-digit authenticator code OR an 8-char
 * backup code — the backend tries the TOTP first, then falls back to a
 * one-time backup code. A "Lost your authenticator?" escape hatch lets an
 * operator who lost their TOTP device (and their backup codes) mint a fresh
 * QR + backup codes with just their password, so a self-hosted user is never
 * permanently locked out of their own machine.
 */

import { useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LogoIcon } from "@/components/brand/Logo";
import { KeyRound, ShieldCheck, AlertTriangle, RotateCcw, Download } from "lucide-react";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { downgradeMode } from "@/lib/modeAuth";
import { buildHeaders, getBase } from "@/services/ftApi.helpers";

interface LoginRouteProps {
  onSuccess: () => void;
  mode: "full" | "pin";
}

/** Pull the base32 secret out of an ``otpauth://`` URI for manual entry. */
function extractTotpSecret(uri: string): string {
  const match = uri.match(/[?&]secret=([^&]+)/i);
  return match ? decodeURIComponent(match[1]) : "";
}

export default function LoginRoute({ onSuccess, mode }: LoginRouteProps) {
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [recovering, setRecovering] = useState(false);

  async function handlePasswordLogin() {
    setIsLoading(true);
    setError("");
    try {
      const resp = await fetch(`${getBase()}/v1/auth/login`, {
        method: "POST",
        headers: buildHeaders(true),
        body: JSON.stringify({ password, totp_code: totpCode }),
      });
      const data = await resp.json();
      if (resp.ok && data.data?.token) {
        useAuthStore.getState().setLoggedIn(
          data.data.token,
          data.data.username,
          data.data.expires_at,
        );
        // Reconcile the persisted UI mode with the freshly-minted JWT.
        // Password login always mints an `explore` JWT. If the UI was last
        // in Live, drop to Explore (never silently re-arm real money — Live
        // requires the explicit PIN dialog). If the UI was in Practice,
        // upgrade the JWT to practice so sandbox orders aren't rejected 403
        // `mode_blocked` (Phase 1 G1: the login-time half of the divergence).
        const uiMode = useModeStore.getState().mode;
        if (uiMode === "live") {
          useModeStore.getState().setMode("explore");
        } else if (uiMode === "practice") {
          try {
            const practiceToken = await downgradeMode("practice", data.data.token);
            useAuthStore.getState().updateToken(practiceToken);
          } catch {
            // Couldn't sync — fall back to Explore rather than leave the UI
            // in a Practice state the JWT doesn't back.
            useModeStore.getState().setMode("explore");
          }
        }
        onSuccess();
      } else {
        setError(data.message || "Invalid credentials.");
      }
    } catch {
      setError("Cannot reach server.");
    } finally {
      setIsLoading(false);
    }
  }

  async function handlePinLogin() {
    setIsLoading(true);
    setError("");
    try {
      // Session-bound PIN unlock (policy D6): the backend requires the current
      // session JWT alongside the PIN. With no (or an expired) token the 401's
      // message tells the operator to do the full password+TOTP login — which
      // is exactly the daily re-auth requirement.
      const headers = buildHeaders(true);
      const authState = useAuthStore.getState();
      const sessionToken = authState.token ?? authState.reauthToken;
      if (sessionToken) headers["Authorization"] = `Bearer ${sessionToken}`;
      const resp = await fetch(`${getBase()}/v1/auth/pin`, {
        method: "POST",
        headers,
        body: JSON.stringify({ pin }),
      });
      const data = await resp.json();
      if (resp.ok && data.data?.token) {
        useAuthStore.getState().setLoggedIn(
          data.data.token,
          useAuthStore.getState().username || "user",
          "",
        );
        useModeStore.getState().setMode("live");
        onSuccess();
      } else {
        setError(data.message || "Invalid PIN.");
      }
    } catch {
      setError("Cannot reach server.");
    } finally {
      setIsLoading(false);
    }
  }

  // 2FA-recovery escape hatch: a self-hosted operator who lost their TOTP device
  // AND their backup codes can still mint fresh ones with just their password.
  if (mode === "full" && recovering) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-surface-base p-6">
        <div className="w-full max-w-sm space-y-6">
          <div className="flex justify-center">
            <LogoIcon size={40} className="text-accent" />
          </div>
          <TwoFactorRecovery onBack={() => setRecovering(false)} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-surface-base p-6">
      <div className="w-full max-w-sm space-y-6">
        {/* Logo */}
        <div className="flex justify-center">
          <LogoIcon size={40} className="text-accent" />
        </div>

        <div className="text-center space-y-1">
          <h1 className="font-heading font-bold text-xl text-text-primary">
            {mode === "pin" ? "Quick Unlock" : "Welcome Back"}
          </h1>
          <p className="text-sm text-text-muted">
            {mode === "pin"
              ? "Enter your PIN to continue"
              : "Enter your password and 2FA code"}
          </p>
        </div>

        {error && (
          <div role="alert" className="flex items-center gap-2 p-3 rounded-lg bg-loss/10 border border-loss/30 text-sm text-loss">
            <AlertTriangle className="size-4 shrink-0" />
            {error}
          </div>
        )}

        {mode === "pin" ? (
          <div className="space-y-4">
            <div>
              <label htmlFor="pin" className="text-xs text-text-secondary font-medium block mb-1.5">
                PIN
              </label>
              <Input
                id="pin"
                type="password"
                inputMode="numeric"
                maxLength={6}
                value={pin}
                onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
                placeholder="6-digit PIN"
                aria-label="Enter your 6-digit PIN"
                className="text-center font-mono text-lg tracking-widest"
                onKeyDown={(e) => e.key === "Enter" && handlePinLogin()}
                autoFocus
              />
            </div>
            <Button
              onClick={handlePinLogin}
              disabled={pin.length !== 6 || isLoading}
              className="w-full"
            >
              <KeyRound className="size-4" />
              {isLoading ? "Verifying..." : "Unlock"}
            </Button>
            <button
              type="button"
              onClick={() => useAuthStore.getState().setLoggedOut()}
              className="w-full text-xs text-text-muted hover:text-text-primary transition-colors"
            >
              Use password instead
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label htmlFor="password" className="text-xs text-text-secondary font-medium block mb-1.5">
                Password
              </label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter password"
                aria-label="Enter your password"
                autoFocus
              />
            </div>
            <div>
              <label htmlFor="totp" className="text-xs text-text-secondary font-medium block mb-1.5">
                2FA or backup code
              </label>
              <Input
                id="totp"
                type="text"
                inputMode="text"
                autoCapitalize="characters"
                maxLength={8}
                value={totpCode}
                // Accept a 6-digit TOTP or an 8-char backup code (upper-hex);
                // the backend tries the authenticator code first, then a code.
                onChange={(e) => setTotpCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8))}
                placeholder="6-digit code or backup code"
                aria-label="Enter your 2FA code"
                className="font-mono tracking-widest"
                onKeyDown={(e) => e.key === "Enter" && handlePasswordLogin()}
              />
            </div>
            <Button
              onClick={handlePasswordLogin}
              disabled={!password || totpCode.length < 6 || isLoading}
              className="w-full"
            >
              <ShieldCheck className="size-4" />
              {isLoading ? "Signing in..." : "Sign In"}
            </Button>
            <button
              type="button"
              onClick={() => { setError(""); setRecovering(true); }}
              className="w-full text-xs text-text-muted hover:text-text-primary transition-colors"
            >
              Lost your authenticator?
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 2FA recovery — password → fresh TOTP QR + backup codes (no session needed)
// ---------------------------------------------------------------------------

function TwoFactorRecovery({ onBack }: { onBack: () => void }) {
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<{ totpUri: string; backupCodes: string[] } | null>(null);
  const [saved, setSaved] = useState(false);

  async function submit() {
    if (!password || loading) return;
    setLoading(true);
    setError("");
    try {
      // Password-only reset (no session) — the backend guards this route with
      // the account password and a 3/hour rate limit, so a shoulder-surfer can
      // neither trigger it nor learn the new secret without the password.
      const resp = await fetch(`${getBase()}/v1/auth/setup/regenerate-2fa`, {
        method: "POST",
        headers: buildHeaders(true),
        body: JSON.stringify({ password }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        setError(data?.message ?? `Reset failed (HTTP ${resp.status}).`);
        return;
      }
      const totpUri = typeof data?.data?.totp_uri === "string" ? data.data.totp_uri : "";
      const backupCodes: string[] = Array.isArray(data?.data?.backup_codes)
        ? data.data.backup_codes.filter((c: unknown): c is string => typeof c === "string")
        : [];
      setResult({ totpUri, backupCodes });
      setPassword("");
    } catch {
      setError("Cannot reach server.");
    } finally {
      setLoading(false);
    }
  }

  function downloadCodes() {
    if (!result) return;
    const body = `FlintTrade Backup Codes\n\nStore these in a safe place.\nEach code can only be used once.\n\n${result.backupCodes.join("\n")}\n`;
    const url = URL.createObjectURL(new Blob([body], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "flinttrade-backup-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
    setSaved(true);
  }

  // Result view — fresh QR + backup codes to save.
  if (result) {
    const secret = extractTotpSecret(result.totpUri);
    return (
      <div className="space-y-5">
        <div className="text-center space-y-1">
          <h1 className="font-heading font-bold text-xl text-text-primary">New 2FA ready</h1>
          <p className="text-sm text-text-muted">Scan this in your authenticator, then sign in.</p>
        </div>

        {result.totpUri && (
          <div className="flex flex-col items-center gap-3">
            <div className="rounded-lg bg-white p-3">
              <QRCodeSVG value={result.totpUri} size={160} aria-label="New 2FA QR code" />
            </div>
            {secret && (
              <p className="text-[11px] text-text-muted text-center">
                Or enter the key manually:
                <br />
                <span className="font-mono text-text-secondary break-all">{secret}</span>
              </p>
            )}
          </div>
        )}

        <div className="space-y-2">
          <p className="text-xs text-text-secondary font-medium">Backup codes (each usable once)</p>
          <div className="grid grid-cols-2 gap-1.5 rounded-lg border border-border-subtle bg-surface-muted p-3">
            {result.backupCodes.map((code) => (
              <span key={code} className="font-mono text-sm text-text-primary text-center tracking-wider">{code}</span>
            ))}
          </div>
          <div role="alert" className="flex items-start gap-2 p-2.5 rounded-lg bg-loss/10 border border-loss/30 text-[11px] text-loss">
            <AlertTriangle className="size-3.5 shrink-0 mt-0.5" />
            <span>Save these now — they are your only recovery if you lose your device again.</span>
          </div>
          <Button type="button" variant="outline" size="sm" onClick={downloadCodes} className="w-full">
            <Download className="size-4" />
            {saved ? "Downloaded" : "Download codes"}
          </Button>
        </div>

        <Button type="button" onClick={onBack} className="w-full">
          Back to sign in
        </Button>
      </div>
    );
  }

  // Password-confirm view.
  return (
    <div className="space-y-5">
      <div className="text-center space-y-1">
        <h1 className="font-heading font-bold text-xl text-text-primary">Reset your 2FA</h1>
        <p className="text-sm text-text-muted">
          Lost your authenticator? Confirm your password to get a fresh QR and backup codes.
        </p>
      </div>

      {error && (
        <div role="alert" className="flex items-center gap-2 p-3 rounded-lg bg-loss/10 border border-loss/30 text-sm text-loss">
          <AlertTriangle className="size-4 shrink-0" />
          {error}
        </div>
      )}

      <div>
        <label htmlFor="recover-password" className="text-xs text-text-secondary font-medium block mb-1.5">
          Password
        </label>
        <Input
          id="recover-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Enter password"
          aria-label="Confirm your password to reset 2FA"
          onKeyDown={(e) => e.key === "Enter" && submit()}
          autoFocus
        />
      </div>

      <Button onClick={submit} disabled={!password || loading} className="w-full">
        <RotateCcw className="size-4" />
        {loading ? "Resetting..." : "Reset 2FA"}
      </Button>
      <button
        type="button"
        onClick={onBack}
        className="w-full text-xs text-text-muted hover:text-text-primary transition-colors"
      >
        Back to sign in
      </button>
    </div>
  );
}
