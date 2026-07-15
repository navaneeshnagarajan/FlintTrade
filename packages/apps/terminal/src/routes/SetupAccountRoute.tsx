/**
 * SetupAccountRoute — one-time account setup wizard (7 steps, 0-indexed).
 *
 * Step 0: Account Security  — username, email, password, optional PIN (POSTs /v1/auth/setup)
 * Step 1: Two-Factor Auth   — warning → QR + backup codes (forward-only once account exists)
 * Step 2: Persona           — Trader / Investor / Beginner
 * Step 3: Broker Connection — OpenAlgo host + API key (or Direct Connect)
 * Step 4: Trading Defaults  — exchange, product, quantity
 * Step 5: Risk Limits       — MTM caps, position size, order rate
 * Step 6: Choose Mode       — Explore / Practice / Live (selecting a mode FINISHES setup)
 *
 * Non-secret progress — `accountCreated`, persona, connection metadata,
 * trading/risk form values, and `currentStep` — is persisted to **localStorage**
 * under the key `flinttrade:setup-progress` so it survives refresh, tab close,
 * and browser restart. TOTP material, backup codes, and broker credentials stay
 * in memory only.
 *
 * Progress is cleared ONLY by explicit user action:
 *   (a) selecting a mode on step 6 (Finish setup)
 *   (b) clicking "Start over" in the header
 *   (c) hitting HTTP 409 on account creation (account already exists → sign in)
 *
 * On completion navigates to /welcome (which shows the sign-in form since an
 * account now exists).
 */

import { useEffect, useMemo, useState } from "react";
import { safeParse } from "@/lib/safeParse";
import { buildHeaders, getBase } from "@/services/ftApi.helpers";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  ShieldCheck,
  Eye,
  EyeOff,
  Download,
  AlertTriangle,
  CheckCircle2,
  Loader2,
} from "lucide-react";
import { QRCodeSVG } from "qrcode.react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import PublicRouteShell from "@/components/layout/PublicRouteShell";
import { StepIndicator } from "@/routes/setup/StepIndicator";
import { PersonaPicker, type Persona } from "@/routes/setup/PersonaStep";
import { ConnectionStep } from "@/routes/setup/ConnectionStep";
import type { ConnectionFormValues } from "@/routes/setup/connectionForm";
import { TradingStep, type TradingDefaultsFormValues } from "@/routes/setup/TradingStep";
import { RiskStep, type RiskFormValues } from "@/routes/setup/RiskStep";
import ModeSelectRoute from "@/routes/ModeSelectRoute";
import { downgradeMode } from "@/lib/modeAuth";
import { useModeStore, type AppMode } from "@/stores/modeStore";
import {
  captureAuthSessionFence,
  isAuthSessionFenceCurrent,
  useAuthStore,
} from "@/stores/authStore";
import { AccountSetupError, setupFlintTradeAccount } from "@/lib/setupAccountApi";
import { persistSetupChoices } from "@/routes/setup/applySetupChoices";

// ---------------------------------------------------------------------------
// Session-storage progress tracking
// ---------------------------------------------------------------------------

const PROGRESS_KEY = "flinttrade:setup-progress";

/**
 * 7 linear steps. TOTP is step 1 (not an invisible sub-phase of step 0).
 *   0: Account Security  (one-way — submitting creates the account)
 *   1: Two-Factor Auth   (one-way — confirmation cannot be undone)
 *   2: Persona
 *   3: Broker Connection
 *   4: Trading Defaults
 *   5: Risk Limits
 *   6: Choose Mode       ("Finish setup" lives on this step)
 *
 * All form values from steps 2–5 are persisted so Back/Next preserve entries.
 */
interface SetupProgress {
  accountCreated: boolean;
  totpUri: string;
  backupCodes: string[];
  persona: Persona | null;
  connection: Partial<ConnectionFormValues> | null;
  trading: Partial<TradingDefaultsFormValues> | null;
  risk: Partial<RiskFormValues> | null;
  mode: AppMode | null;
  displayName: string;
  /** 0..6 — the step index the user is currently viewing. */
  currentStep: number;
}

const personaEnum = z.enum(["trader", "investor", "beginner"]);
const appModeEnum = z.enum(["explore", "practice", "live"]);

const persistedSetupProgressSchema = z.object({
  accountCreated: z.boolean(),
  persona: personaEnum.nullable(),
  connection: z
    .object({
      host: z.string().optional(),
      port: z.string().optional(),
      wsPort: z.string().optional(),
    })
    .nullable(),
  trading: z
    .object({
      defaultExchange: z.string().optional(),
      defaultProduct: z.string().optional(),
      defaultQty: z.number().optional(),
    })
    .nullable(),
  risk: z
    .object({
      maxPositionLots: z.number().optional(),
      mtmStoploss: z.number().optional(),
      mtmTarget: z.number().optional(),
      maxOrdersPerMinute: z.number().optional(),
    })
    .nullable(),
  mode: appModeEnum.nullable(),
  displayName: z.string().optional().default(""),
  currentStep: z.number().int().min(0).max(6),
});

const EMPTY_PROGRESS: SetupProgress = {
  accountCreated: false,
  totpUri: "",
  backupCodes: [],
  persona: null,
  connection: null,
  trading: null,
  risk: null,
  mode: null,
  displayName: "",
  currentStep: 0,
};

// Persisted in `localStorage` (not sessionStorage) so progress survives
// tab close, browser restart, and accidental refreshes. The only auto-clear
// paths are: (a) user clicks "Finish setup" on the final step, or (b)
// explicit user opt-out via the "Start over" button on the account form.
// We deliberately do NOT auto-wipe based on auth-store heuristics —
// stale client state must never erase a user's in-progress setup.
function loadProgress(): SetupProgress | null {
  try {
    const raw = localStorage.getItem(PROGRESS_KEY);
    const persisted = safeParse(raw, persistedSetupProgressSchema);
    if (!persisted) return null;
    const progress: SetupProgress = {
      ...persisted,
      // Recovery material and broker credentials are deliberately never
      // restored from browser storage. Older records are rewritten below so
      // secrets left by previous versions are removed on first load.
      totpUri: "",
      backupCodes: [],
      connection: persisted.connection
        ? { ...persisted.connection, apiKey: "" }
        : null,
    };
    saveProgress(progress);
    return progress;
  } catch {
    return null;
  }
}

function saveProgress(progress: SetupProgress): void {
  try {
    localStorage.setItem(PROGRESS_KEY, JSON.stringify({
      accountCreated: progress.accountCreated,
      persona: progress.persona,
      connection: progress.connection
        ? {
            host: progress.connection.host,
            port: progress.connection.port,
            wsPort: progress.connection.wsPort,
          }
        : null,
      trading: progress.trading,
      risk: progress.risk,
      mode: progress.mode,
      displayName: progress.displayName,
      currentStep: progress.currentStep,
    }));
  } catch {
    // Storage quota or privacy mode — non-critical, continue in-memory.
  }
}

function clearProgress(): void {
  try {
    localStorage.removeItem(PROGRESS_KEY);
  } catch {
    // Non-critical.
  }
}

// ---------------------------------------------------------------------------
// Step 1 — Account security schema
// ---------------------------------------------------------------------------

const accountSchema = z.object({
  username: z
    .string()
    .min(3, "At least 3 characters")
    .max(32, "Maximum 32 characters")
    .regex(/^[a-zA-Z0-9_-]+$/, "Letters, numbers, _ and - only"),
  email: z.string().email("Enter a valid email address"),
  password: z
    .string()
    .min(8, "At least 8 characters")
    .regex(/[A-Z]/, "Include at least one uppercase letter")
    .regex(/[0-9]/, "Include at least one number")
    .regex(/[^a-zA-Z0-9]/, "Include at least one special character"),
  confirmPassword: z.string(),
  pin: z.string().optional(),
  confirmPin: z.string().optional(),
}).refine((d) => d.password === d.confirmPassword, {
  message: "Passwords do not match",
  path: ["confirmPassword"],
}).refine((d) => !d.pin || (d.pin.length === 6 && /^\d{6}$/.test(d.pin)), {
  message: "PIN must be exactly 6 digits",
  path: ["pin"],
}).refine((d) => !d.pin || d.pin === d.confirmPin, {
  message: "PINs do not match",
  path: ["confirmPin"],
});

type AccountFormValues = z.infer<typeof accountSchema>;

// ---------------------------------------------------------------------------
// Password strength meter
// ---------------------------------------------------------------------------

function passwordStrength(password: string): { score: number; label: string; color: string } {
  if (password.length === 0) return { score: 0, label: "", color: "" };
  let score = 0;
  if (password.length >= 8)  score++;
  if (password.length >= 12) score++;
  if (/[A-Z]/.test(password)) score++;
  if (/[0-9]/.test(password)) score++;
  if (/[^a-zA-Z0-9]/.test(password)) score++;

  if (score <= 2) return { score, label: "Weak",   color: "bg-loss" };
  if (score === 3) return { score, label: "Fair",   color: "bg-amber-500" };
  if (score === 4) return { score, label: "Good",   color: "bg-profit/70" };
  return              { score, label: "Strong", color: "bg-profit" };
}

// ---------------------------------------------------------------------------
// Step 1: Account Security
// ---------------------------------------------------------------------------

interface AccountSecurityStepProps {
  onComplete: (values: AccountFormValues, totpUri: string, backupCodes: string[]) => void;
  onBack: () => void;
}

function AccountSecurityStep({ onComplete, onBack }: AccountSecurityStepProps) {
  const navigate = useNavigate();
  const setLoggedOut = useAuthStore((s) => s.setLoggedOut);
  const setLoggedInIfCurrent = useAuthStore((s) => s.setLoggedInIfCurrent);
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [serverError, setServerError] = useState("");
  const [accountExists, setAccountExists] = useState(false);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<AccountFormValues>({ resolver: zodResolver(accountSchema) });

  const watchedPassword = watch("password", "");
  const watchedPin = watch("pin", "");
  const strength = passwordStrength(watchedPassword);

  async function onSubmit(values: AccountFormValues) {
    const requestFence = captureAuthSessionFence();
    setIsLoading(true);
    setServerError("");
    setAccountExists(false);
    try {
      const result = await setupFlintTradeAccount({
        username: values.username,
        email: values.email,
        password: values.password,
        pin: values.pin || "",
      });
      // /auth/setup mints an explore-mode session so the rest of the wizard
      // (broker connection behind the G9 write guard, mode selection behind the
      // D6 session-bound PIN) is authenticated. Without it those steps 401.
      // Fall back to logged-out only if an older backend returned no token.
      if (result.token) {
        if (!setLoggedInIfCurrent(result.token, values.username, "", requestFence)) return;
      } else {
        if (!isAuthSessionFenceCurrent(requestFence)) return;
        setLoggedOut();
      }
      onComplete(values, result.totpUri, result.backupCodes);
    } catch (error) {
      if (!isAuthSessionFenceCurrent(requestFence)) return;
      if (error instanceof AccountSetupError && error.kind === "account-exists") {
        // Account already exists — don't wedge. Route the user to login,
        // which is the only sensible next step. Clear any stale progress
        // so the next /setup-account entry won't try to re-submit.
        clearProgress();
        setAccountExists(true);
        setServerError(
          error.message || "An account already exists on this machine. Sign in to continue.",
        );
        return;
      }
      setServerError(
        error instanceof Error
          ? error.message
          : "Setup failed. Please try again.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-5" noValidate>
      <div className="flex items-center gap-2 text-accent mb-1">
        <ShieldCheck className="size-4 shrink-0" />
        <span className="text-xs text-text-secondary">Credentials stored locally — never sent to any server except your own instance.</span>
      </div>

      {serverError && (
        <div
          className={`flex items-start gap-3 p-3 rounded-lg border text-sm ${
            accountExists
              ? "bg-accent/10 border-accent/30 text-text-primary"
              : "bg-loss/10 border-loss/30 text-loss"
          }`}
          role="alert"
        >
          <AlertTriangle className={`size-4 shrink-0 mt-0.5 ${accountExists ? "text-accent" : ""}`} />
          <div className="flex-1 space-y-2">
            <div>{serverError}</div>
            {accountExists && (
              <Button
                type="button"
                size="sm"
                onClick={() => navigate("/welcome", { replace: true })}
              >
                Go to sign-in
              </Button>
            )}
          </div>
        </div>
      )}

      {/* Username */}
      <div className="space-y-1.5">
        <Label htmlFor="sa-username" className="text-xs text-text-secondary uppercase tracking-wider">
          Username <span className="text-loss">*</span>
        </Label>
        <Input
          id="sa-username"
          autoFocus
          autoComplete="username"
          placeholder="e.g. alice"
          aria-label="Choose a username"
          {...register("username")}
        />
        {errors.username && <p role="alert" className="text-xs text-loss">{errors.username.message}</p>}
      </div>

      {/* Email */}
      <div className="space-y-1.5">
        <Label htmlFor="sa-email" className="text-xs text-text-secondary uppercase tracking-wider">
          Email <span className="text-loss">*</span>
        </Label>
        <Input
          id="sa-email"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          aria-label="Enter your email address"
          {...register("email")}
        />
        {errors.email && <p role="alert" className="text-xs text-loss">{errors.email.message}</p>}
        <p className="text-xs text-text-muted">Used for password reset only. Never shared with third parties.</p>
      </div>

      {/* Password + strength meter */}
      <div className="space-y-1.5">
        <Label htmlFor="sa-password" className="text-xs text-text-secondary uppercase tracking-wider">
          Password <span className="text-loss">*</span>
        </Label>
        <div className="relative">
          <Input
            id="sa-password"
            type={showPassword ? "text" : "password"}
            autoComplete="new-password"
            placeholder="Strong password"
            aria-label="Create a strong password"
            className="pr-10"
            {...register("password")}
          />
          <button
            type="button"
            onClick={() => setShowPassword((v) => !v)}
            aria-label={showPassword ? "Hide password" : "Show password"}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary transition-colors"
          >
            {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        </div>
        {/* Strength bar */}
        {watchedPassword.length > 0 && (
          <div className="space-y-1">
            <div className="flex gap-1" aria-hidden="true">
              {[1, 2, 3, 4, 5].map((n) => (
                <div
                  key={n}
                  className={`h-1 flex-1 rounded-full transition-colors duration-300 ${
                    n <= strength.score ? strength.color : "bg-border-default"
                  }`}
                />
              ))}
            </div>
            {strength.label && (
              <p className={`text-xs ${strength.score <= 2 ? "text-loss" : strength.score === 3 ? "text-amber-400" : "text-profit"}`}>
                {strength.label} password
              </p>
            )}
          </div>
        )}
        {errors.password && <p role="alert" className="text-xs text-loss">{errors.password.message}</p>}
      </div>

      {/* Confirm Password — only shown once the user starts typing a password */}
      {watchedPassword.length > 0 && (
        <div className="space-y-1.5">
          <Label htmlFor="sa-confirm-password" className="text-xs text-text-secondary uppercase tracking-wider">
            Confirm Password <span className="text-loss">*</span>
          </Label>
          <Input
            id="sa-confirm-password"
            type="password"
            autoComplete="new-password"
            placeholder="Re-enter password"
            aria-label="Confirm your password"
            {...register("confirmPassword")}
          />
          {errors.confirmPassword && <p role="alert" className="text-xs text-loss">{errors.confirmPassword.message}</p>}
        </div>
      )}

      {/* PIN — optional */}
      <div className="space-y-1.5">
        <Label htmlFor="sa-pin" className="text-xs text-text-secondary uppercase tracking-wider">
          6-digit PIN <span className="normal-case text-text-muted font-normal">(optional)</span>
        </Label>
        <p className="text-xs text-text-muted">Optional — enables quick unlock and lock screen.</p>
        <Input
          id="sa-pin"
          type="password"
          inputMode="numeric"
          autoComplete="new-password"
          maxLength={6}
          placeholder="••••••"
          aria-label="Create a 6-digit PIN (optional)"
          className="text-center font-mono text-lg tracking-widest max-w-40"
          {...register("pin")}
        />
        {errors.pin && <p role="alert" className="text-xs text-loss">{errors.pin.message}</p>}
      </div>

      {/* Confirm PIN — only shown once the user starts typing a PIN */}
      {watchedPin && watchedPin.length > 0 && (
        <div className="space-y-1.5">
          <Label htmlFor="sa-confirm-pin" className="text-xs text-text-secondary uppercase tracking-wider">
            Confirm PIN
          </Label>
          <Input
            id="sa-confirm-pin"
            type="password"
            inputMode="numeric"
            autoComplete="new-password"
            maxLength={6}
            placeholder="••••••"
            aria-label="Re-enter your 6-digit PIN"
            className="text-center font-mono text-lg tracking-widest max-w-40"
            {...register("confirmPin")}
          />
          {errors.confirmPin && <p role="alert" className="text-xs text-loss">{errors.confirmPin.message}</p>}
        </div>
      )}

      <div className="flex justify-between items-center mt-6">
        <Button variant="ghost" onClick={onBack} type="button">
          Back
        </Button>
        <Button type="submit" disabled={isLoading}>
          {isLoading ? <Loader2 className="size-4 animate-spin mr-2" /> : null}
          {isLoading ? "Setting up…" : "Continue"}
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// TOTP + Backup Codes display (shown after successful Step 1 API call)
// ---------------------------------------------------------------------------

interface TotpDisplayProps {
  totpUri: string;
  backupCodes: string[];
  onConfirmed: () => void;
  /** Replaces the current TOTP URI + backup codes after a "Reset 2FA" action. */
  onTotpRegenerated: (uri: string, codes: string[]) => void;
  /** Called after a successful "Delete account" reset. */
  onAccountDeleted: () => void;
}

/** "reset-2fa" regenerates the TOTP; "delete-account" wipes the user entirely. */
type EscapeAction = "reset-2fa" | "delete-account" | null;

function TotpDisplay({
  totpUri,
  backupCodes,
  onConfirmed,
  onTotpRegenerated,
  onAccountDeleted,
}: TotpDisplayProps) {
  const hasRecoveryMaterial = Boolean(totpUri && backupCodes.length > 0);
  const [phase, setPhase] = useState<"warning" | "qr">("warning");
  const [downloaded, setDownloaded] = useState(false);
  const [qrVisible, setQrVisible] = useState(false);

  // Escape-hatch state: when the user clicks "Reset 2FA" or "Delete account"
  // we reveal an inline password-confirm form (instead of a modal) so the
  // flow stays within the card.
  const [escapeAction, setEscapeAction] = useState<EscapeAction>(null);
  const [escapePassword, setEscapePassword] = useState("");
  const [escapeLoading, setEscapeLoading] = useState(false);
  const [escapeError, setEscapeError] = useState("");

  // 2FA is a forward-only gate. The in-step back only toggles qr → warning
  // so the user can re-read the warning before scanning.
  function handleInternalBack() {
    if (phase === "qr") setPhase("warning");
  }

  function cancelEscape() {
    setEscapeAction(null);
    setEscapePassword("");
    setEscapeError("");
    setEscapeLoading(false);
  }

  async function submitEscape() {
    if (!escapeAction || !escapePassword) return;
    setEscapeLoading(true);
    setEscapeError("");
    const endpoint =
      escapeAction === "reset-2fa"
        ? `${getBase()}/v1/auth/setup/regenerate-2fa`
        : `${getBase()}/v1/auth/setup/reset`;
    try {
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: buildHeaders(true),
        body: JSON.stringify({ password: escapePassword }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        setEscapeError(data?.message ?? `Request failed (HTTP ${resp.status}).`);
        return;
      }
      if (escapeAction === "reset-2fa") {
        onTotpRegenerated(data?.data?.totp_uri ?? "", data?.data?.backup_codes ?? []);
        cancelEscape();
        setPhase("qr"); // jump straight to the fresh QR
      } else {
        onAccountDeleted();
      }
    } catch {
      setEscapeError("Cannot reach server. Is the backend running?");
    } finally {
      setEscapeLoading(false);
    }
  }

  function downloadCodes() {
    const content = backupCodes.join("\n");
    const blob = new Blob([`FlintTrade Backup Codes\n\nStore these in a safe place.\nEach code can only be used once.\n\n${content}\n`], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "flinttrade-backup-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
    setDownloaded(true);
  }

  // Shared escape-hatch block (rendered on both warning and qr phases).
  // Gives the user two explicit exits: "Reset 2FA" (keep account, new QR)
  // and "Delete account & start over" (wipe and re-run step 0).
  function EscapeHatches() {
    if (escapeAction) {
      const title =
        escapeAction === "reset-2fa"
          ? "Reset 2FA — confirm with your password"
          : "Delete account — confirm with your password";
      const confirmLabel =
        escapeAction === "reset-2fa" ? "Reset 2FA" : "Delete account";
      return (
        <div className="mt-4 rounded-lg border border-loss/30 bg-loss/5 p-3 space-y-2">
          <p className="text-xs text-text-primary font-medium">{title}</p>
          <p className="text-[11px] text-text-muted">
            {escapeAction === "reset-2fa"
              ? "Your old QR and backup codes will be invalidated. You'll scan a fresh QR on the next screen."
              : "The account will be wiped from this machine. You can re-create it with a different username or email."}
          </p>
          <Input
            type="password"
            autoFocus
            autoComplete="current-password"
            placeholder="Your password"
            value={escapePassword}
            onChange={(e) => setEscapePassword(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void submitEscape(); }}
            aria-label="Confirm password"
          />
          {escapeError && (
            <p role="alert" className="text-xs text-loss">{escapeError}</p>
          )}
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={cancelEscape}
              disabled={escapeLoading}
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => void submitEscape()}
              disabled={escapeLoading || !escapePassword}
              className={escapeAction === "delete-account" ? "bg-loss hover:bg-loss/90" : ""}
            >
              {escapeLoading ? <Loader2 className="size-3.5 animate-spin mr-1.5" /> : null}
              {confirmLabel}
            </Button>
          </div>
        </div>
      );
    }
    return (
      <div className="mt-4 pt-3 border-t border-border-default flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-text-muted/80">
        <span className="text-text-muted/60">Need to change something?</span>
        <button
          type="button"
          onClick={() => setEscapeAction("reset-2fa")}
          className="underline decoration-dotted underline-offset-4 hover:text-text-primary"
        >
          Reset 2FA
        </button>
        <button
          type="button"
          onClick={() => setEscapeAction("delete-account")}
          className="underline decoration-dotted underline-offset-4 hover:text-loss"
        >
          Delete account &amp; start over
        </button>
      </div>
    );
  }

  // Phase 1: Warning — explain what 2FA is, what's locked in, and the exits.
  if (phase === "warning") {
    return (
      <div className="space-y-5">
        <div className="flex items-center gap-2 text-accent">
          <ShieldCheck className="size-5 shrink-0" />
          <h3 className="text-sm font-semibold text-text-primary">Two-Factor Authentication (2FA)</h3>
        </div>

        <div className="rounded-lg border border-accent/30 bg-accent/5 p-4 space-y-3">
          <p className="text-xs text-text-secondary leading-relaxed">
            2FA adds an extra layer of security to your account. After setup, every login will require a one-time code from your authenticator app.
          </p>
          <ul className="space-y-2 text-xs text-text-secondary">
            <li className="flex items-start gap-2">
              <span className="text-accent mt-0.5 shrink-0">•</span>
              <span>You will need an authenticator app — <strong className="text-text-primary">Google Authenticator</strong>, <strong className="text-text-primary">Authy</strong>, or <strong className="text-text-primary">Microsoft Authenticator</strong> all work.</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-accent mt-0.5 shrink-0">•</span>
              <span>Download one from your app store now if you don&apos;t have it.</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-loss mt-0.5 shrink-0">!</span>
              <span><strong className="text-text-primary">Important:</strong> You will also receive backup codes on the next screen. Save them somewhere safe — they are your only recovery option if you lose your phone.</span>
            </li>
          </ul>
        </div>

        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 space-y-1.5">
          <p className="text-xs text-amber-400 font-medium flex items-center gap-1.5">
            <AlertTriangle className="size-3.5" />
            Heads up — 2FA is a one-way step
          </p>
          <p className="text-[11px] text-text-secondary leading-relaxed">
            Your account is already created on this machine. Once you continue
            and scan the QR, you cannot come back to change your username,
            email, or password without signing in first. If you need to change
            any of those, use <strong>Delete account &amp; start over</strong>{" "}
            below. If you only need a new QR (wrong device scanned, lost
            phone), use <strong>Reset 2FA</strong>.
          </p>
        </div>

        {!hasRecoveryMaterial && (
          <div
            role="alert"
            className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-text-secondary"
          >
            For security, the QR seed and backup codes were not retained after the page was
            closed or refreshed. Use <strong className="text-text-primary">Reset 2FA</strong>{" "}
            below and confirm your password to generate fresh recovery material.
          </div>
        )}

        <div className="flex justify-end items-center mt-6">
          <Button onClick={() => setPhase("qr")} disabled={!hasRecoveryMaterial}>
            I&apos;m ready — show QR code
          </Button>
        </div>

        <EscapeHatches />
      </div>
    );
  }

  // Phase 2: QR code + backup codes
  return (
    <div className="space-y-6">
      {/* 2FA QR */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-text-primary">Scan with Authenticator</h3>
        <p className="text-xs text-text-muted">
          Use Google Authenticator, Authy, or any TOTP app. Scan the QR code or enter the key manually.
        </p>
        {totpUri ? (
          <div className="flex flex-col items-center gap-3">
            {qrVisible ? (
              <>
                <div className="rounded-lg border border-border-default bg-white p-2">
                  <QRCodeSVG
                    value={totpUri}
                    size={180}
                    bgColor="transparent"
                    fgColor="#000000"
                  />
                </div>
                <button
                  type="button"
                  onClick={() => setQrVisible(false)}
                  className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded px-2 py-1"
                  aria-label="Hide QR code"
                >
                  <EyeOff className="size-3.5" />
                  Hide QR Code
                </button>
              </>
            ) : (
              <div className="flex flex-col items-center gap-2">
                <button
                  type="button"
                  onClick={() => setQrVisible(true)}
                  className="flex items-center gap-2 px-4 py-3 rounded-lg border border-border-default bg-surface-card hover:bg-surface-raised text-sm text-text-secondary hover:text-text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  aria-label="Reveal QR code"
                >
                  <Eye className="size-4" />
                  Reveal QR Code
                </button>
                <p className="text-xs text-text-muted text-center">
                  QR code is hidden for security. Click to reveal.
                </p>
              </div>
            )}
          </div>
        ) : (
          <p className="text-xs text-text-muted italic">2FA QR code not available — configure later in Settings.</p>
        )}
      </div>

      {/* Backup codes */}
      {backupCodes.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-text-primary">Backup Codes</h3>
          <p className="text-xs text-text-muted">
            Save these codes. Each can be used once if you lose access to your Authenticator.
          </p>
          <div className="grid grid-cols-2 gap-1.5 p-3 rounded-lg bg-surface-card border border-border-default font-mono text-xs text-text-secondary">
            {backupCodes.map((code) => (
              <span key={code} className="select-all">{code}</span>
            ))}
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full gap-2"
            onClick={downloadCodes}
          >
            <Download className="size-3.5" />
            Download backup codes
            {downloaded && <CheckCircle2 className="size-3.5 text-profit ml-auto" />}
          </Button>
        </div>
      )}

      <div className="flex justify-between items-center mt-6">
        <Button variant="ghost" onClick={handleInternalBack} type="button">
          Back
        </Button>
        <Button onClick={onConfirmed} disabled={!hasRecoveryMaterial}>
          I have saved my codes — Continue
        </Button>
      </div>

      <EscapeHatches />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2: Persona
// ---------------------------------------------------------------------------

interface PersonaStepWrapperProps {
  initialSelected?: Persona | null;
  onComplete: (persona: Persona) => void;
  onBack: () => void;
}

function PersonaStepWrapper({ initialSelected, onComplete, onBack }: PersonaStepWrapperProps) {
  const [selected, setSelected] = useState<Persona | null>(initialSelected ?? null);

  return (
    <div className="space-y-6">
      <PersonaPicker selected={selected} onSelect={setSelected} />
      <div className="flex justify-between items-center mt-6">
        <Button variant="ghost" onClick={onBack} type="button">
          Back
        </Button>
        <Button
          onClick={() => selected && onComplete(selected)}
          disabled={!selected}
        >
          Continue
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main wizard component
// ---------------------------------------------------------------------------

const STEP_LABELS = [
  "Account Security",
  "Two-Factor Auth",
  "Persona",
  "Broker Connection",
  "Trading Defaults",
  "Risk Limits",
  "Choose Mode",
] as const;

const TOTAL_STEPS = STEP_LABELS.length; // 7

export default function SetupAccountRoute() {
  const navigate = useNavigate();
  const setMode = useModeStore((s) => s.setMode);

  // ---------------------------------------------------------------------------
  // Load persisted progress. We trust localStorage as the source of truth for
  // "where was the user" and only invalidate it on explicit user action
  // (finish setup, or "Start over" button). Auto-wiping based on client
  // auth-store heuristics was the source of multiple state-loss bugs.
  // ---------------------------------------------------------------------------
  const initialProgress: SetupProgress = loadProgress() ?? EMPTY_PROGRESS;

  const [currentStep, setCurrentStep] = useState(() =>
    Math.min(initialProgress.currentStep, TOTAL_STEPS - 1),
  );
  const modeSelectionFence = useMemo(
    () => currentStep === TOTAL_STEPS - 1 ? captureAuthSessionFence() : null,
    [currentStep],
  );
  const [accountCreated, setAccountCreated] = useState(initialProgress.accountCreated);
  const [totpUri, setTotpUri] = useState(initialProgress.totpUri);
  const [backupCodes, setBackupCodes] = useState<string[]>(initialProgress.backupCodes);
  const [persona, setPersona] = useState<Persona | null>(initialProgress.persona);
  const [connection, setConnection] = useState<Partial<ConnectionFormValues> | null>(
    initialProgress.connection,
  );
  const [trading, setTrading] = useState<Partial<TradingDefaultsFormValues> | null>(
    initialProgress.trading,
  );
  const [risk, setRisk] = useState<Partial<RiskFormValues> | null>(initialProgress.risk);
  const [displayName, setDisplayName] = useState(initialProgress.displayName);
  // Mode-step notice: shown when the server refuses to mint a Practice
  // session, so the user never finishes setup with a UI mode the JWT
  // doesn't back (Phase 1 G1 divergence class).
  const [modeSyncError, setModeSyncError] = useState("");

  // Persist on every state change so reloads / navigations never lose entries.
  // Keyed off explicit `accountCreated` — never derived from secondary fields
  // (an empty TOTP URI from the server must NOT disable persistence).
  useEffect(() => {
    if (!accountCreated) return;
    saveProgress({
      accountCreated: true,
      totpUri,
      backupCodes,
      persona,
      connection,
      trading,
      risk,
      mode: null,
      displayName,
      currentStep,
    });
  }, [currentStep, totpUri, backupCodes, persona, connection, trading, risk, displayName, accountCreated]);

  // No auto-wipe based on authStatus. Progress is cleared only by an explicit
  // user action: "Finish setup" on the final step or the "Start over" button
  // on the account form. The 409 branch in AccountSecurityStep also clears
  // because at that point the user has confirmed the account already exists
  // server-side and wants to sign in instead.
  function handleStartOver() {
    clearProgress();
    setAccountCreated(false);
    setCurrentStep(0);
    setTotpUri("");
    setBackupCodes([]);
    setPersona(null);
    setConnection(null);
    setTrading(null);
    setRisk(null);
    setDisplayName("");
  }

  // ---------------------------------------------------------------------------
  // Step handlers — each advances currentStep; the effect above persists.
  // ---------------------------------------------------------------------------

  function handleAccountComplete(values: AccountFormValues, uri: string, codes: string[]) {
    // Persist synchronously so a reload before the effect fires still lands on step 1.
    saveProgress({
      accountCreated: true,
      totpUri: uri,
      backupCodes: codes,
      persona: null,
      connection: null,
      trading: null,
      risk: null,
      mode: null,
      displayName: values.username,
      currentStep: 1,
    });
    setAccountCreated(true);
    setTotpUri(uri);
    setBackupCodes(codes);
    setDisplayName(values.username);
    setCurrentStep(1);
  }

  function handleTotpConfirmed() { setCurrentStep(2); }

  function handleTotpRegenerated(uri: string, codes: string[]) {
    setTotpUri(uri);
    setBackupCodes(codes);
    // The persist effect picks this up automatically; no need to save inline.
  }

  function handleAccountDeleted() {
    // Server wiped the account. Authoritatively reset everything: clear
    // localStorage, flip the auth store back to setup-required, bounce to
    // /welcome which will render the "Get Started" CTA again.
    clearProgress();
    setAccountCreated(false);
    setTotpUri("");
    setBackupCodes([]);
    setPersona(null);
    setConnection(null);
    setTrading(null);
    setRisk(null);
    setDisplayName("");
    setCurrentStep(0);
    useAuthStore.getState().setSetupRequired();
    navigate("/welcome", { replace: true });
  }

  function handlePersonaComplete(p: Persona) {
    setPersona(p);
    setCurrentStep(3);
  }

  function handleConnectionComplete(values: ConnectionFormValues) {
    setConnection(values);
    setCurrentStep(4);
  }

  function handleTradingComplete(values: TradingDefaultsFormValues) {
    setTrading(values);
    setCurrentStep(5);
  }

  function handleRiskComplete(values: RiskFormValues) {
    setRisk(values);
    setCurrentStep(6);
  }

  async function handleModeSelect(mode: AppMode, liveSessionToken?: string) {
    setModeSyncError("");
    if (mode === "practice") {
      // /auth/setup minted an EXPLORE-mode JWT. The server reads the mode from
      // the JWT claim (never a client header), so flipping the UI to Practice
      // without minting a practice token leaves the first sandbox order
      // rejected 403 mode_blocked — the setup-wizard half of the Phase 1 G1
      // divergence (LoginRoute already reconciles the login-time half).
      try {
        const authState = useAuthStore.getState();
        const practiceToken = await downgradeMode(
          "practice",
          authState.token,
        );
        if (!useAuthStore.getState().updateToken(
          practiceToken,
          authState.sessionGeneration,
        )) return;
      } catch {
        // Do NOT finish setup with a PRACTICE badge over an Explore JWT —
        // surface the failure and let the user retry Practice or pick
        // Explore explicitly (both keep UI and JWT in lockstep).
        setModeSyncError(
          "Practice mode could not be enabled (the server did not issue a Practice session). " +
            "Retry Practice, or continue with Explore and switch to Practice later from the TopBar.",
        );
        return;
      }
    }
    if (mode === "live") {
      if (
        !liveSessionToken ||
        !modeSelectionFence ||
        !useAuthStore.getState().setLoggedInIfCurrent(
          liveSessionToken,
          displayName || "Trader",
          "",
          modeSelectionFence,
        )
      ) return;
    }
    setMode(mode);
    const landingRoute = persistSetupChoices({
      persona: persona ?? "trader",
      connection,
      tradingDefaults: trading,
      riskLimits: risk,
      name: displayName || "Trader",
      interests: [],
    });
    if (mode === "live") {
      clearProgress();
      navigate(landingRoute, { replace: true });
      return;
    }
    // Setup finished — clear persisted progress and route to sign-in.
    clearProgress();
    navigate("/welcome", { replace: true });
  }

  // ---------------------------------------------------------------------------
  // Back navigation
  //   Steps 0–2 are "sealed" once submitted (account creation + 2FA
  //   confirmation cannot be undone). Back from any of these returns to
  //   /welcome so the user can sign in. Steps 3–6 freely decrement and
  //   the previously entered values are preserved via saveProgress.
  // ---------------------------------------------------------------------------

  function handleBack() {
    if (currentStep <= 2) {
      navigate("/welcome", { replace: true });
      return;
    }
    setCurrentStep((s) => s - 1);
  }

  // completedCount = steps the user has fully submitted to reach currentStep.
  const completedCount = currentStep;
  const remaining = TOTAL_STEPS - currentStep - 1;

  return (
    <PublicRouteShell
      mainLabel="Account setup"
      maxWidth="sm"
      contentClassName="py-4 sm:py-5"
      eyebrow="Account Setup"
      title="Set up FlintTrade"
      subtitle={`Step ${currentStep + 1} of ${TOTAL_STEPS} - ${STEP_LABELS[currentStep]}`}
    >
      <div className="space-y-4">
        {currentStep > 0 && currentStep < 6 && (
          <div className="flex items-center justify-between gap-3 rounded-xl border border-border-default/70 bg-surface-card/60 px-4 py-2 shadow-xl shadow-black/10 backdrop-blur-xl">
            <p className="text-xs text-text-muted">
              {completedCount} of {TOTAL_STEPS} completed
              {remaining > 0 ? ` - ${remaining} remaining` : " - last step"}
            </p>
            <Button
              type="button"
              variant="ghost"
              size="xs"
              className="text-text-muted hover:text-text-primary"
              onClick={() => {
                if (
                  window.confirm(
                    "Start over from the beginning? Your in-progress entries (persona, broker, trading, risk) will be cleared. The account itself is kept on the server - you will need to sign in to delete it.",
                  )
                ) {
                  handleStartOver();
                }
              }}
            >
              Start over
            </Button>
          </div>
        )}

        {/* Step indicator */}
        <StepIndicator
          total={TOTAL_STEPS}
          current={currentStep}
          onStepClick={(i) => {
            // Only allow jumping to already-completed reversible steps (3+).
            // Steps 0–2 are sealed (account + 2FA submitted on server).
            if (i >= 3 && i < currentStep) setCurrentStep(i);
          }}
        />

        {/* Step body — Mode step renders its own full layout */}
        {currentStep === 6 ? (
          <div className="rounded-xl border border-border-default/70 bg-surface-card/70 p-4 shadow-2xl shadow-black/20 backdrop-blur-xl">
            {modeSyncError && (
              <div
                role="alert"
                className="mb-4 flex items-start gap-3 rounded-lg border border-loss/30 bg-loss/10 p-3 text-sm text-loss"
              >
                <AlertTriangle className="size-4 shrink-0 mt-0.5" />
                <span>{modeSyncError}</span>
              </div>
            )}
            <ModeSelectRoute onSelect={handleModeSelect} />
          </div>
        ) : (
          <div className="rounded-xl border border-border-default/70 bg-surface-card/70 p-4 shadow-2xl shadow-black/20 backdrop-blur-xl">
            {currentStep === 0 && (
              <AccountSecurityStep
                onComplete={handleAccountComplete}
                onBack={handleBack}
              />
            )}

            {currentStep === 1 && (
              <TotpDisplay
                totpUri={totpUri}
                backupCodes={backupCodes}
                onConfirmed={handleTotpConfirmed}
                onTotpRegenerated={handleTotpRegenerated}
                onAccountDeleted={handleAccountDeleted}
              />
            )}

            {currentStep === 2 && (
              <PersonaStepWrapper
                initialSelected={persona}
                onComplete={handlePersonaComplete}
                onBack={handleBack}
              />
            )}

            {currentStep === 3 && (
              <ConnectionStep
                defaultValues={connection ?? undefined}
                onComplete={handleConnectionComplete}
              />
            )}

            {currentStep === 4 && (
              <TradingStep
                defaultValues={trading ?? undefined}
                onComplete={handleTradingComplete}
              />
            )}

            {currentStep === 5 && (
              <RiskStep
                defaultValues={risk ?? undefined}
                onComplete={handleRiskComplete}
              />
            )}
          </div>
        )}

        {/* Back button for steps 3–5 (ConnectionStep, TradingStep, RiskStep
            render their own Continue buttons). Step 6 (Mode) and 0–2 each
            own their own Back button. */}
        {currentStep >= 3 && currentStep <= 5 && (
          <div className="flex justify-start">
              <Button variant="ghost" onClick={handleBack} type="button">
              Back
            </Button>
          </div>
        )}
      </div>
    </PublicRouteShell>
  );
}
