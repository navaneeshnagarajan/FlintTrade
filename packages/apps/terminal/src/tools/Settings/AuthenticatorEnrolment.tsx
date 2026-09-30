/**
 * Post-setup authenticator enrolment.
 *
 * An operator who chose "Set up later" still has no totp_enabled flag.
 * Settings → Security is the path back: password confirms a fresh QR
 * (`POST /v1/auth/setup/regenerate-2fa`), then a live code enrols it
 * (`POST /v1/auth/totp/enable`).
 */

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { RefreshCw, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { isTotpEnabledFlag } from "@/hooks/useTotpEnrolled";
import {
  enableFlintTradeTotp,
  regenerateFlintTradeTotp,
  type TotpEnrolmentMaterial,
} from "@/lib/setupAccountApi";
import { getAuthStatus, type AuthStatusData } from "@/services/ftApi";
import { TextInput } from "./shared";

function manualKey(uri: string): string {
  const match = uri.match(/[?&]secret=([^&]+)/i);
  return match ? decodeURIComponent(match[1]) : "";
}

export function AuthenticatorEnrolment() {
  const qc = useQueryClient();
  const authStatusQuery = useQuery<AuthStatusData>({
    queryKey: ["ft", "auth", "status"],
    queryFn: getAuthStatus,
    staleTime: 30_000,
    retry: 1,
  });
  const serverEnrolled = isTotpEnabledFlag(authStatusQuery.data?.totp_enabled);

  const [password, setPassword] = useState("");
  const [material, setMaterial] = useState<TotpEnrolmentMaterial | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [justEnrolled, setJustEnrolled] = useState(false);
  const enrolled = justEnrolled || serverEnrolled;

  async function showQr() {
    if (!password || busy) return;
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const next = await regenerateFlintTradeTotp(password);
      setMaterial(next);
      setPassword("");
    } catch (err) {
      setMaterial(null);
      setError(err instanceof Error && err.message ? err.message : "Could not start authenticator enrolment.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmCode() {
    if (code.length !== 6 || busy) return;
    setBusy(true);
    setError(null);
    try {
      await enableFlintTradeTotp(code);
      setMaterial(null);
      setCode("");
      setJustEnrolled(true);
      setSaved("Authenticator enrolled. Live can use it once a PIN and a broker are in place.");
      await qc.invalidateQueries({ queryKey: ["ft", "auth", "status"] });
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "Could not confirm the authenticator.");
    } finally {
      setBusy(false);
    }
  }

  const secret = material ? manualKey(material.totpUri) : "";

  return (
    <div
      id="authenticator-enrolment"
      data-testid="authenticator-enrolment"
      className="rounded border border-border-default bg-surface-card p-4 space-y-3"
    >
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          Authenticator
        </p>
        {authStatusQuery.isSuccess && (
          <Badge
            variant="outline"
            className={`text-xxs px-1.5 py-0 ${
              enrolled
                ? "border-profit/40 text-profit"
                : "border-warning/40 text-warning"
            }`}
          >
            {enrolled ? "Authenticator enrolled" : "Not enrolled"}
          </Badge>
        )}
      </div>

      {authStatusQuery.isLoading && (
        <div className="flex items-center gap-2 text-xs text-text-muted">
          <RefreshCw size={12} className="animate-spin" />
          Checking authenticator status…
        </div>
      )}

      {authStatusQuery.isSuccess && enrolled && !material && (
        <p className="text-xxs text-text-muted">
          An authenticator is enrolled. Live still needs a PIN and a connected broker.
        </p>
      )}

      {authStatusQuery.isSuccess && !enrolled && !material && (
        <>
          <p className="text-xxs text-text-muted">
            Live stays locked until you enrol an authenticator. Confirm your account
            password to get a QR code, then enter the 6-digit code from your app.
          </p>
          <TextInput
            type="password"
            value={password}
            onChange={setPassword}
            placeholder="Account password"
            aria-label="Password to enrol authenticator"
          />
          {error && (
            <p className="text-xxs text-loss" role="alert">{error}</p>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => { void showQr(); }}
            disabled={!password || busy}
            className="flex items-center gap-1.5 text-xs h-7"
          >
            {busy ? <RefreshCw size={11} className="animate-spin" /> : <ShieldCheck size={11} />}
            {busy ? "Preparing…" : "Show authenticator QR"}
          </Button>
        </>
      )}

      {material && (
        <div className="space-y-3">
          <div className="flex flex-col items-center gap-2">
            <div className="rounded-lg bg-white p-3">
              <QRCodeSVG value={material.totpUri} size={148} aria-label="Authenticator QR code" />
            </div>
            {secret && (
              <p className="text-[11px] text-text-muted text-center">
                Or enter the key manually:
                <br />
                <span className="font-mono text-text-secondary break-all" aria-label="Manual authenticator key">
                  {secret}
                </span>
              </p>
            )}
          </div>
          {material.backupCodes.length > 0 && (
            <div className="space-y-1">
              <p className="text-xxs text-text-secondary">Backup codes (each usable once)</p>
              <div className="grid grid-cols-2 gap-1.5 rounded border border-border-default p-2 font-mono text-xxs text-text-secondary">
                {material.backupCodes.map((backup) => (
                  <span key={backup} className="select-all">{backup}</span>
                ))}
              </div>
            </div>
          )}
          <TextInput
            type="text"
            inputMode="numeric"
            maxLength={6}
            value={code}
            onChange={(value) => setCode(value.replace(/\D/g, "").slice(0, 6))}
            placeholder="6-digit authenticator code"
            aria-label="Authenticator enrolment code"
          />
          {error && (
            <p className="text-xxs text-loss" role="alert">{error}</p>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => { void confirmCode(); }}
            disabled={code.length !== 6 || busy}
            className="flex items-center gap-1.5 text-xs h-7"
          >
            {busy ? "Confirming…" : "Confirm enrolment"}
          </Button>
        </div>
      )}

      {saved && (
        <p className="text-xxs text-profit" role="status">{saved}</p>
      )}
    </div>
  );
}
