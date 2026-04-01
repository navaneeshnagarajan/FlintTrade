/**
 * LoginRoute — daily login screen (password + TOTP or PIN).
 *
 * Rendered inside /welcome flow for returning users.
 * Not a standalone route — it's a component used by WelcomeRoute.
 */

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LogoIcon } from "@/components/brand/Logo";
import { Lock, KeyRound, ShieldCheck, AlertTriangle } from "lucide-react";
import { useAuthStore } from "@/stores/authStore";

interface LoginRouteProps {
  onSuccess: () => void;
  mode: "full" | "pin";
}

export default function LoginRoute({ onSuccess, mode }: LoginRouteProps) {
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  async function handlePasswordLogin() {
    setIsLoading(true);
    setError("");
    try {
      const resp = await fetch("/ft-api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password, totp_code: totpCode }),
      });
      const data = await resp.json();
      if (resp.ok && data.data?.token) {
        useAuthStore.getState().setLoggedIn(
          data.data.token,
          data.data.username,
          data.data.expires_at,
        );
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
      const resp = await fetch("/ft-api/v1/auth/pin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin }),
      });
      const data = await resp.json();
      if (resp.ok && data.data?.token) {
        useAuthStore.getState().setLoggedIn(
          data.data.token,
          useAuthStore.getState().username || "user",
          "",
        );
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
          <div className="flex items-center gap-2 p-3 rounded-lg bg-loss/10 border border-loss/30 text-sm text-loss">
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
                2FA Code
              </label>
              <Input
                id="totp"
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ""))}
                placeholder="6-digit code from Authenticator"
                aria-label="Enter your 2FA code"
                className="font-mono tracking-widest"
                onKeyDown={(e) => e.key === "Enter" && handlePasswordLogin()}
              />
            </div>
            <Button
              onClick={handlePasswordLogin}
              disabled={!password || totpCode.length !== 6 || isLoading}
              className="w-full"
            >
              <ShieldCheck className="size-4" />
              {isLoading ? "Signing in..." : "Sign In"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

// Unused import kept for completeness — Lock icon available for future use
void Lock;
