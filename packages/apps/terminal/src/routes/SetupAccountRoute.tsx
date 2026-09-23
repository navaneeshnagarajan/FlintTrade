/**
 * SetupAccountRoute — the authoritative /setup wizard.
 *
 * Required steps (Step N of 3 only):
 *   0: Create operator — username, email, password, optional PIN
 *   1: Vault — open the credential vault with a master password
 *   2: Practice desk — affirm Practice and land on the desk
 *
 * Later / Skip (never counted, never shown before the affirm, never
 * block Practice): authenticator, broker connect, LLM, Monitoring,
 * trading defaults, and risk limits. They open on the Practice desk
 * after landing. Persona is not a first-run gate.
 * First run has no Live unlock.
 *
 * Non-secret progress is persisted to localStorage under
 * `flinttrade:setup-progress`. TOTP material, backup codes, broker
 * credentials, and the master password stay out of browser storage.
 *
 * Progress is cleared ONLY by explicit user action:
 *   (a) opening the Practice desk
 *   (b) clicking "Start over" (wipes the unfinished account)
 *   (c) deleting the account from the vault or authenticator recovery
 */

import { useEffect, useMemo, useState } from "react";
import { safeParse } from "@/lib/safeParse";
import { buildHeaders, getBase } from "@/services/ftApi.helpers";
import { useNavigate } from "react-router";
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
import type { Persona } from "@/routes/setup/PersonaStep";
import { ConnectionStep } from "@/routes/setup/ConnectionStep";
import type { ConnectionFormValues } from "@/routes/setup/connectionForm";
import type { TradingDefaultsFormValues } from "@/routes/setup/TradingStep";
import type { RiskFormValues } from "@/routes/setup/RiskStep";
import { LlmStep, type LlmFormValues } from "@/routes/setup/LlmStep";
import { normaliseLlmHost, providerSelection } from "@/lib/llmProviders";
import { TradingStep } from "@/routes/setup/TradingStep";
import { RiskStep } from "@/routes/setup/RiskStep";
import { useSettingsStore } from "@/stores/settingsStore";
import { downgradeMode } from "@/lib/modeAuth";
import { useModeStore, type AppMode } from "@/stores/modeStore";
import {
  captureAuthSessionFence,
  isAuthSessionFenceCurrent,
  useAuthStore,
} from "@/stores/authStore";
import {
  AccountSetupError,
  enableFlintTradeTotp,
  openFlintTradeVault,
  setupFlintTradeAccount,
} from "@/lib/setupAccountApi";
import { persistSetupChoices } from "@/routes/setup/applySetupChoices";
import {
  REQUIRED_SETUP_STEP_COUNT,
  REQUIRED_SETUP_STEP_LABELS,
  type OptionalSetupPanel,
} from "@/routes/setupRouting";

// ---------------------------------------------------------------------------
// Session-storage progress tracking
// ---------------------------------------------------------------------------

const PROGRESS_KEY = "flinttrade:setup-progress";

/**
 * Required steps only. Optional panels are not stored as step indexes.
 *   0: Create operator (one-way — submitting creates the account)
 *   1: Vault
 *   2: Practice desk
 *
 * Legacy records may still carry persona, trading, and risk values. They
 * are kept so a refresh does not drop them, and they are not gates.
 */
interface SetupProgress {
  accountCreated: boolean;
  /** True once the credential vault has been opened on this machine. */
  vaultOpened: boolean;
  totpUri: string;
  backupCodes: string[];
  persona: Persona | null;
  connection: Partial<ConnectionFormValues> | null;
  trading: Partial<TradingDefaultsFormValues> | null;
  risk: Partial<RiskFormValues> | null;
  mode: AppMode | null;
  displayName: string;
  /** 0..2 — the required step the operator is on. */
  currentStep: number;
}

const personaEnum = z.enum(["trader", "investor", "beginner"]);
const appModeEnum = z.enum(["explore", "practice", "live"]);

const persistedSetupProgressSchema = z.object({
  accountCreated: z.boolean(),
  vaultOpened: z.boolean().optional().default(false),
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
  /** Accept legacy 0..6 records, then clamp them onto the required path. */
  currentStep: z.number().int().min(0).max(6),
});

const EMPTY_PROGRESS: SetupProgress = {
  accountCreated: false,
  vaultOpened: false,
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

function requiredStepFor(progress: { accountCreated: boolean; vaultOpened: boolean }): number {
  if (!progress.accountCreated) return 0;
  if (!progress.vaultOpened) return 1;
  return 2;
}

// Module-scoped, in-memory-only cache of the step-2 recovery material (TOTP
// URI + backup codes). Recovery material is deliberately NEVER written to
// browser storage, but the wizard's component state is lost when the route
// remounts — and installing the explore-mode session token right after
// account creation flips the auth store and remounts the tree. Without this
// cache a brand-new account landed on step 2 with the QR button disabled and
// a misleading "closed or refreshed" recovery message. Module scope survives
// remounts within this JS session and dies on a real refresh or close,
// exactly matching that message; it is cleared on start-over, account
// deletion, and when the operator skips authenticator setup on the desk.
// Opening the Practice desk keeps it so the later tray can still show the QR.
let sessionRecoveryMaterial: { totpUri: string; backupCodes: string[] } | null = null;

/** Test-only: drop the in-memory recovery-material cache between tests. */
export function clearSessionRecoveryMaterialForTests(): void {
  sessionRecoveryMaterial = null;
}

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
    const vaultOpened = persisted.vaultOpened === true;
    const progress: SetupProgress = {
      ...persisted,
      vaultOpened,
      // Recovery material and broker credentials are deliberately never
      // restored from browser storage. Older records are rewritten below so
      // secrets left by previous versions are removed on first load.
      totpUri: "",
      backupCodes: [],
      connection: persisted.connection
        ? { ...persisted.connection, apiKey: "" }
        : null,
      currentStep: requiredStepFor({
        accountCreated: persisted.accountCreated,
        vaultOpened,
      }),
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
      vaultOpened: progress.vaultOpened,
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

/** Set once the operator opens the Practice desk. Not a required step. */
export const PRACTICE_LATER_KEY = "flinttrade:setup-later";

export function markPracticeLaterPending(): void {
  try {
    localStorage.setItem(PRACTICE_LATER_KEY, "1");
  } catch {
    // Storage quota or privacy mode — the desk still opens.
  }
}

export function clearPracticeLaterPending(): void {
  try {
    localStorage.removeItem(PRACTICE_LATER_KEY);
  } catch {
    // Non-critical.
  }
}

function practiceLaterPending(): boolean {
  try {
    return localStorage.getItem(PRACTICE_LATER_KEY) === "1";
  } catch {
    return false;
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
  /** Account already exists — jump to the 2FA wipe hatches instead of 409. */
  onAccountAlreadyExists: () => void;
}

function AccountSecurityStep({ onComplete, onBack, onAccountAlreadyExists }: AccountSecurityStepProps) {
  const setLoggedOut = useAuthStore((s) => s.setLoggedOut);
  const setLoggedInIfCurrent = useAuthStore((s) => s.setLoggedInIfCurrent);
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [serverError, setServerError] = useState("");

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
        // Unfinished first-run: open the 2FA step so Delete / Start over
        // can wipe the account instead of a dead-end 409.
        onAccountAlreadyExists();
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
          className="flex items-start gap-3 p-3 rounded-lg border text-sm bg-loss/10 border-loss/30 text-loss"
          role="alert"
        >
          <AlertTriangle className="size-4 shrink-0 mt-0.5" />
          <div className="flex-1 space-y-2">
            <div>{serverError}</div>
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
  /** Defer authenticator enrolment and continue the wizard. */
  onSetUpLater: () => void;
}

/** "reset-2fa" regenerates the TOTP; "delete-account" wipes the user entirely. */
type EscapeAction = "reset-2fa" | "delete-account" | null;

function TotpDisplay({
  totpUri,
  backupCodes,
  onConfirmed,
  onTotpRegenerated,
  onAccountDeleted,
  onSetUpLater,
}: TotpDisplayProps) {
  const hasRecoveryMaterial = Boolean(totpUri && backupCodes.length > 0);
  // The base32 secret from the otpauth URI, shown as a selectable manual
  // entry key alongside the QR (an authenticator on this same machine cannot
  // scan its own screen).
  const manualTotpKey = useMemo(() => {
    try {
      return new URL(totpUri).searchParams.get("secret") ?? "";
    } catch {
      return "";
    }
  }, [totpUri]);
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
  const [enrolCode, setEnrolCode] = useState("");
  const [enrolLoading, setEnrolLoading] = useState(false);
  const [enrolError, setEnrolError] = useState("");

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
            An authenticator is optional for Explore and Practice. Enrol it now, or choose
            Set up later and use your password. Live unlock still requires the authenticator
            and your PIN.
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

        <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2 mt-6">
          <Button
            type="button"
            variant="outline"
            onClick={onSetUpLater}
          >
            Set up later
          </Button>
          <Button onClick={() => setPhase("qr")} disabled={!hasRecoveryMaterial}>
            I&apos;m ready — show QR code
          </Button>
        </div>
        <p className="text-[11px] text-text-muted text-right">
          Explore and Practice work with your password only. Enrol the
          authenticator before unlocking Live.
        </p>

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
            {qrVisible && manualTotpKey && (
              // The intro copy promises manual entry, and an authenticator on
              // THIS machine (desktop password managers, browser extensions)
              // cannot scan its own screen — without this key those users had
              // no path through 2FA at all.
              <div className="w-full space-y-1">
                <p className="text-[11px] uppercase tracking-wide text-text-muted text-center">
                  Manual entry key
                </p>
                <p
                  className="select-all break-all text-center font-mono text-xs text-text-secondary rounded-lg border border-border-default bg-surface-card px-3 py-2"
                  aria-label="Manual TOTP entry key"
                >
                  {manualTotpKey}
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

      <div className="space-y-2">
        <Label htmlFor="sa-totp-enrol" className="text-xs text-text-secondary uppercase tracking-wider">
          Authenticator code
        </Label>
        <Input
          id="sa-totp-enrol"
          type="text"
          inputMode="numeric"
          maxLength={6}
          value={enrolCode}
          onChange={(e) => {
            setEnrolCode(e.target.value.replace(/\D/g, "").slice(0, 6));
            if (enrolError) setEnrolError("");
          }}
          placeholder="6-digit code"
          aria-label="Enter the 6-digit authenticator code to enrol"
          className="font-mono tracking-widest max-w-48"
        />
        {enrolError && (
          <p role="alert" className="text-xs text-loss">{enrolError}</p>
        )}
      </div>

      <div className="flex flex-col-reverse sm:flex-row sm:justify-between sm:items-center gap-2 mt-6">
        <Button variant="ghost" onClick={handleInternalBack} type="button">
          Back
        </Button>
        <div className="flex flex-col-reverse sm:flex-row gap-2">
          <Button type="button" variant="outline" onClick={onSetUpLater}>
            Set up later
          </Button>
          <Button
            onClick={() => {
              void (async () => {
                if (enrolCode.length !== 6) {
                  setEnrolError("Enter the 6-digit authenticator code.");
                  return;
                }
                setEnrolLoading(true);
                setEnrolError("");
                try {
                  await enableFlintTradeTotp(enrolCode);
                  onConfirmed();
                } catch (error) {
                  setEnrolError(
                    error instanceof Error ? error.message : "Could not confirm authenticator.",
                  );
                } finally {
                  setEnrolLoading(false);
                }
              })();
            }}
            disabled={!hasRecoveryMaterial || enrolLoading}
          >
            {enrolLoading ? <Loader2 className="size-4 animate-spin mr-2" /> : null}
            {enrolLoading ? "Confirming…" : "I have saved my codes — Continue"}
          </Button>
        </div>
      </div>

      <EscapeHatches />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2: Vault
// ---------------------------------------------------------------------------

const vaultSchema = z.object({
  masterPassword: z.string().min(8, "At least 8 characters"),
  confirmMasterPassword: z.string(),
}).refine((values) => values.masterPassword === values.confirmMasterPassword, {
  message: "Master passwords do not match",
  path: ["confirmMasterPassword"],
});

type VaultFormValues = z.infer<typeof vaultSchema>;

interface VaultStepProps {
  onOpened: () => void;
  onAccountDeleted: () => void;
}

function VaultStep({ onOpened, onAccountDeleted }: VaultStepProps) {
  const [phase, setPhase] = useState<"checking" | "form" | "ready">("checking");
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [serverError, setServerError] = useState("");
  const [resetOpen, setResetOpen] = useState(false);
  const [resetPassword, setResetPassword] = useState("");
  const [resetError, setResetError] = useState("");
  const [resetLoading, setResetLoading] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<VaultFormValues>({ resolver: zodResolver(vaultSchema) });

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const result = await openFlintTradeVault("");
        if (cancelled) return;
        setPhase(result.alreadyPresent ? "ready" : "form");
      } catch {
        if (!cancelled) setPhase("form");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit(values: VaultFormValues) {
    setIsLoading(true);
    setServerError("");
    try {
      await openFlintTradeVault(values.masterPassword);
      onOpened();
    } catch (error) {
      setServerError(
        error instanceof Error ? error.message : "The vault could not be opened.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  async function submitReset() {
    if (!resetPassword) return;
    setResetLoading(true);
    setResetError("");
    try {
      const resp = await fetch(`${getBase()}/v1/auth/setup/reset`, {
        method: "POST",
        headers: buildHeaders(true),
        body: JSON.stringify({ password: resetPassword }),
      });
      const data = await resp.json() as { message?: string };
      if (!resp.ok) {
        setResetError(data?.message ?? `Request failed (HTTP ${resp.status}).`);
        return;
      }
      onAccountDeleted();
    } catch {
      setResetError("Cannot reach the server to delete the account.");
    } finally {
      setResetLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2 text-accent">
        <ShieldCheck className="size-5 shrink-0" />
        <h3 className="text-sm font-semibold text-text-primary">Vault</h3>
      </div>
      <p className="text-xs text-text-secondary leading-relaxed">
        Open the credential vault with a master password. It stays on this
        machine, it is not your sign-in password, and it is never shown again
        after you save it.
      </p>

      {phase === "checking" && (
        <p className="text-xs text-text-muted">Checking the vault…</p>
      )}

      {phase === "ready" && (
        <div className="space-y-4">
          <p className="text-sm text-text-primary">
            The vault is already open on this machine.
          </p>
          <div className="flex justify-end">
            <Button type="button" onClick={onOpened}>
              Continue
            </Button>
          </div>
        </div>
      )}

      {phase === "form" && (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          {serverError && (
            <div role="alert" className="flex items-start gap-3 p-3 rounded-lg border text-sm bg-loss/10 border-loss/30 text-loss">
              <AlertTriangle className="size-4 shrink-0 mt-0.5" />
              <span>{serverError}</span>
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="sa-master-password" className="text-xs text-text-secondary uppercase tracking-wider">
              Master password <span className="text-loss">*</span>
            </Label>
            <div className="relative">
              <Input
                id="sa-master-password"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                aria-label="Master password"
                className="pr-10"
                {...register("masterPassword")}
              />
              <Button
                type="button"
                variant="ghost"
                size="xs"
                onClick={() => setShowPassword((value) => !value)}
                aria-label={showPassword ? "Hide master password" : "Show master password"}
                className="absolute right-1.5 top-1/2 -translate-y-1/2"
              >
                {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </Button>
            </div>
            {errors.masterPassword && (
              <p role="alert" className="text-xs text-loss">{errors.masterPassword.message}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sa-confirm-master-password" className="text-xs text-text-secondary uppercase tracking-wider">
              Confirm master password <span className="text-loss">*</span>
            </Label>
            <Input
              id="sa-confirm-master-password"
              type="password"
              autoComplete="new-password"
              aria-label="Confirm master password"
              {...register("confirmMasterPassword")}
            />
            {errors.confirmMasterPassword && (
              <p role="alert" className="text-xs text-loss">{errors.confirmMasterPassword.message}</p>
            )}
          </div>
          <div className="flex justify-end">
            <Button type="submit" disabled={isLoading}>
              {isLoading ? <Loader2 className="size-4 animate-spin mr-2" /> : null}
              {isLoading ? "Opening vault…" : "Open vault"}
            </Button>
          </div>
        </form>
      )}

      <div className="pt-3 border-t border-border-default">
        {resetOpen ? (
          <div className="space-y-2">
            <Input
              type="password"
              value={resetPassword}
              onChange={(event) => setResetPassword(event.target.value)}
              aria-label="Confirm password to delete the account"
            />
            {resetError && <p role="alert" className="text-xs text-loss">{resetError}</p>}
            <div className="flex gap-2">
              <Button type="button" variant="outline" size="sm" onClick={() => setResetOpen(false)}>
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={() => void submitReset()}
                disabled={resetLoading || !resetPassword}
              >
                Delete account
              </Button>
            </div>
          </div>
        ) : (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setResetOpen(true)}
            className="text-[11px] text-text-muted hover:text-loss"
          >
            Delete account &amp; start over
          </Button>
        )}
      </div>
    </div>
  );
}

function PracticeDeskStep() {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-text-primary">Practice desk</h3>
      <p className="text-xs text-text-secondary leading-relaxed">
        Open the Practice desk. Orders stay simulated. Live is not part of
        setup and stays locked until you choose it later.
      </p>
    </div>
  );
}

type LaterPanel = OptionalSetupPanel | "trading" | "risk";

const LATER_ACTIONS: ReadonlyArray<{
  id: LaterPanel;
  title: string;
  detail: string;
}> = [
  {
    id: "totp",
    title: "Two-factor authentication",
    detail: "Optional. Practice does not need an authenticator.",
  },
  {
    id: "broker",
    title: "Broker connect",
    detail: "Optional. Practice does not need a broker.",
  },
  {
    id: "llm",
    title: "LLM",
    detail: "Optional. You can choose a model later.",
  },
  {
    id: "monitoring",
    title: "Monitoring",
    detail: "Optional. System health stays in Settings.",
  },
  {
    id: "trading",
    title: "Trading defaults",
    detail: "Optional. Defaults stay in Settings until you set them.",
  },
  {
    id: "risk",
    title: "Risk",
    detail: "Optional. Limits stay in Settings until you set them.",
  },
];

/**
 * Later/Skip tray on the Practice desk. Renders nothing until the operator
 * has affirmed Practice. Skipping a panel does not leave the desk, and the
 * tray never shows Step N of M.
 */
export function PracticeLaterSetup() {
  const [pending, setPending] = useState(practiceLaterPending);
  const [panel, setPanel] = useState<LaterPanel | null>(null);
  const [skipped, setSkipped] = useState<ReadonlySet<LaterPanel>>(() => new Set());
  const [totpUri, setTotpUri] = useState(sessionRecoveryMaterial?.totpUri ?? "");
  const [backupCodes, setBackupCodes] = useState<string[]>(
    sessionRecoveryMaterial?.backupCodes ?? [],
  );

  if (!pending) return null;

  function skip(id: LaterPanel) {
    setSkipped((current) => {
      const next = new Set(current);
      next.add(id);
      return next;
    });
    if (id === "totp") sessionRecoveryMaterial = null;
    setPanel(null);
  }

  function dismiss() {
    clearPracticeLaterPending();
    sessionRecoveryMaterial = null;
    setPending(false);
    setPanel(null);
  }

  function rememberChoices(patch: {
    tradingDefaults?: TradingDefaultsFormValues | null;
    riskLimits?: RiskFormValues | null;
    llm?: LlmFormValues | null;
  }) {
    const settings = useSettingsStore.getState();
    if (patch.tradingDefaults) {
      settings.setTradingDefaults({
        defaultExchange: patch.tradingDefaults.defaultExchange,
        defaultProduct: patch.tradingDefaults.defaultProduct,
        defaultQty: patch.tradingDefaults.defaultQty,
      });
    }
    if (patch.riskLimits) settings.setRiskLimits(patch.riskLimits);
    if (patch.llm) {
      const { provider, authMode } = providerSelection(patch.llm.provider);
      settings.setLLMSetupDraft({
        provider,
        authMode,
        model: patch.llm.model.trim(),
        host: normaliseLlmHost(provider, (patch.llm.host ?? "").trim()),
      });
    }
    setPanel(null);
  }

  return (
    <section
      aria-label="Optional setup"
      className="shrink-0 border-b border-border-default bg-surface-card/80 px-3 py-3"
    >
      <div className="mx-auto flex max-w-3xl flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-text-primary">Optional</p>
            <p className="text-xs text-text-muted">
              You can skip this. Practice is already open.
            </p>
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={dismiss}>
            Close
          </Button>
        </div>

        {panel === null && (
          <ul className="grid gap-2 sm:grid-cols-2">
            {LATER_ACTIONS.map((item) => (
              <li
                key={item.id}
                className="rounded-lg border border-border-default p-3 space-y-2"
              >
                <div>
                  <p className="text-sm text-text-primary">
                    {item.title}
                    {skipped.has(item.id) ? <span className="text-text-muted"> — later</span> : null}
                  </p>
                  <p className="text-xs text-text-muted">{item.detail}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    aria-label={`Set up ${item.title}`}
                    onClick={() => setPanel(item.id)}
                  >
                    Set up
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Skip ${item.title}`}
                    onClick={() => skip(item.id)}
                  >
                    Later
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}

        {panel === "totp" && (
          <TotpDisplay
            totpUri={totpUri}
            backupCodes={backupCodes}
            onConfirmed={() => setPanel(null)}
            onTotpRegenerated={(uri, codes) => {
              sessionRecoveryMaterial = { totpUri: uri, backupCodes: codes };
              setTotpUri(uri);
              setBackupCodes(codes);
            }}
            onAccountDeleted={() => {
              clearPracticeLaterPending();
              sessionRecoveryMaterial = null;
              setPending(false);
            }}
            onSetUpLater={() => skip("totp")}
          />
        )}

        {panel === "broker" && (
          <ConnectionStep onComplete={() => setPanel(null)} />
        )}

        {panel === "llm" && (
          <div className="space-y-3">
            <div className="flex justify-end">
              <Button type="button" variant="outline" aria-label="Skip LLM" onClick={() => skip("llm")}>
                Later
              </Button>
            </div>
            <LlmStep onComplete={(values) => rememberChoices({ llm: values })} />
          </div>
        )}

        {panel === "monitoring" && (
          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-text-primary">Monitoring</h3>
            <p className="text-xs text-text-secondary leading-relaxed">
              Monitoring is optional. Practice does not need it. You can open
              system health later in Settings.
            </p>
            <div className="flex justify-end">
              <Button type="button" variant="outline" aria-label="Skip Monitoring" onClick={() => skip("monitoring")}>
                Later
              </Button>
            </div>
          </div>
        )}

        {panel === "trading" && (
          <div className="space-y-3">
            <div className="flex justify-end">
              <Button
                type="button"
                variant="outline"
                aria-label="Skip Trading defaults"
                onClick={() => skip("trading")}
              >
                Later
              </Button>
            </div>
            <TradingStep onComplete={(values) => rememberChoices({ tradingDefaults: values })} />
          </div>
        )}

        {panel === "risk" && (
          <div className="space-y-3">
            <div className="flex justify-end">
              <Button type="button" variant="outline" aria-label="Skip Risk" onClick={() => skip("risk")}>
                Later
              </Button>
            </div>
            <RiskStep onComplete={(values) => rememberChoices({ riskLimits: values })} />
          </div>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main wizard component
// ---------------------------------------------------------------------------

export interface SetupAccountRouteProps {
  /** Requested required step. A deep link cannot skip the vault. */
  requestedStep?: number;
  /**
   * Optional panel from a legacy deep link. Ignored on the wizard so
   * Trading Defaults, Risk, Broker, and the other later panels cannot
   * appear before the Practice affirm.
   */
  requestedOptional?: OptionalSetupPanel;
}

function resolveInitialStep(progress: SetupProgress, requestedStep: number | undefined): number {
  const required = requiredStepFor(progress);
  if (required < 2) return required;
  if (requestedStep === 1) return 1;
  return 2;
}

export default function SetupAccountRoute({
  requestedStep,
}: SetupAccountRouteProps = {}) {
  const navigate = useNavigate();
  const setMode = useModeStore((s) => s.setMode);

  // Load persisted progress. localStorage is the source of truth for where
  // the operator stopped. It is cleared only by opening the Practice desk,
  // Start over, or deleting the account.
  const [initialProgress] = useState<SetupProgress>(() => loadProgress() ?? EMPTY_PROGRESS);

  const [currentStep, setCurrentStep] = useState(() =>
    resolveInitialStep(initialProgress, requestedStep),
  );
  const [accountCreated, setAccountCreated] = useState(initialProgress.accountCreated);
  const [vaultOpened, setVaultOpened] = useState(initialProgress.vaultOpened);
  // Storage never carries recovery material, so a remount recovers it from
  // the in-memory session cache (see sessionRecoveryMaterial above).
  const [totpUri, setTotpUri] = useState(
    initialProgress.totpUri || sessionRecoveryMaterial?.totpUri || "",
  );
  const [backupCodes, setBackupCodes] = useState<string[]>(
    initialProgress.backupCodes.length > 0
      ? initialProgress.backupCodes
      : sessionRecoveryMaterial?.backupCodes ?? [],
  );
  const [persona, setPersona] = useState<Persona | null>(initialProgress.persona);
  const [connection, setConnection] = useState<Partial<ConnectionFormValues> | null>(
    initialProgress.connection,
  );
  const [trading, setTrading] = useState<Partial<TradingDefaultsFormValues> | null>(
    initialProgress.trading,
  );
  const [risk, setRisk] = useState<Partial<RiskFormValues> | null>(initialProgress.risk);
  const [llm, setLlm] = useState<LlmFormValues | null>(null);
  const [displayName, setDisplayName] = useState(initialProgress.displayName);
  // Shown when the server refuses to mint a Practice session, so setup
  // never finishes on a badge the JWT does not back.
  const [modeSyncError, setModeSyncError] = useState("");

  useEffect(() => {
    if (!accountCreated) return;
    saveProgress({
      accountCreated: true,
      vaultOpened,
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
  }, [currentStep, totpUri, backupCodes, persona, connection, trading, risk, displayName, accountCreated, vaultOpened]);

  // No auto-wipe based on authStatus. Progress is cleared only by an explicit
  // user action: "Finish setup" on the final step or the "Start over" button
  // on the account form. The 409 branch in AccountSecurityStep also clears
  // because at that point the user has confirmed the account already exists
  // server-side and wants to sign in instead.
  async function handleStartOver() {
    try {
      const resp = await fetch(`${getBase()}/v1/auth/setup/reset`, {
        method: "POST",
        headers: buildHeaders(true),
        body: JSON.stringify({}),
      });
      if (!resp.ok) {
        window.alert(
          "Could not wipe the unfinished account. Use Delete account and start over and confirm your password.",
        );
        return;
      }
    } catch {
      window.alert("Cannot reach the server to wipe the unfinished account.");
      return;
    }
    clearProgress();
    sessionRecoveryMaterial = null;
    setAccountCreated(false);
    setVaultOpened(false);
    setCurrentStep(0);
    setTotpUri("");
    setBackupCodes([]);
    setPersona(null);
    setConnection(null);
    setTrading(null);
    setRisk(null);
    setLlm(null);
    setDisplayName("");
    useAuthStore.getState().setSetupRequired();
  }

  // ---------------------------------------------------------------------------
  // Step handlers — each advances currentStep; the effect above persists.
  // ---------------------------------------------------------------------------

  function handleAccountComplete(values: AccountFormValues, uri: string, codes: string[]) {
    // Persist synchronously so a reload before the effect fires still lands on step 1.
    saveProgress({
      accountCreated: true,
      vaultOpened: false,
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
    sessionRecoveryMaterial = { totpUri: uri, backupCodes: codes };
    setAccountCreated(true);
    setTotpUri(uri);
    setBackupCodes(codes);
    setDisplayName(values.username);
    setCurrentStep(1);
  }

  function handleAccountAlreadyExists() {
    saveProgress({
      accountCreated: true,
      vaultOpened: false,
      totpUri: "",
      backupCodes: [],
      persona,
      connection,
      trading,
      risk,
      mode: null,
      displayName,
      currentStep: 1,
    });
    setAccountCreated(true);
    setVaultOpened(false);
    setCurrentStep(1);
  }

  function handleAccountDeleted() {
    // Server wiped the account. Authoritatively reset everything: clear
    // localStorage, flip the auth store back to setup-required, bounce to
    // /welcome which will render the "Get Started" CTA again.
    clearProgress();
    sessionRecoveryMaterial = null;
    setAccountCreated(false);
    setVaultOpened(false);
    setTotpUri("");
    setBackupCodes([]);
    setPersona(null);
    setConnection(null);
    setTrading(null);
    setRisk(null);
    setLlm(null);
    setDisplayName("");
    setCurrentStep(0);
    useAuthStore.getState().setSetupRequired();
    navigate("/welcome", { replace: true });
  }

  function handleVaultOpened() {
    saveProgress({
      accountCreated: true,
      vaultOpened: true,
      totpUri,
      backupCodes,
      persona,
      connection,
      trading,
      risk,
      mode: null,
      displayName,
      currentStep: 2,
    });
    setVaultOpened(true);
    setCurrentStep(2);
  }

  async function handleOpenPractice() {
    setModeSyncError("");
    // /auth/setup minted an EXPLORE-mode JWT. The server reads the mode from
    // the JWT claim, so the Practice desk needs a Practice session before
    // the first sandbox order.
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
      setModeSyncError(
        "Practice mode could not be enabled (the server did not issue a Practice session). Retry opening the Practice desk.",
      );
      return;
    }
    setMode("practice");
    const landingRoute = persistSetupChoices({
      persona: persona ?? "trader",
      connection,
      tradingDefaults: trading,
      riskLimits: risk,
      llm,
      name: displayName || "Trader",
      interests: [],
    });
    markPracticeLaterPending();
    clearProgress();
    navigate(landingRoute, { replace: true });
  }

  function handleBack() {
    if (currentStep <= 1) {
      navigate("/welcome", { replace: true });
      return;
    }
    setCurrentStep(1);
  }

  const label = REQUIRED_SETUP_STEP_LABELS[currentStep] ?? REQUIRED_SETUP_STEP_LABELS[0];
  const progressLabel = `Step ${currentStep + 1} of ${REQUIRED_SETUP_STEP_COUNT} - ${label}`;
  const completedCount = currentStep;
  const remaining = REQUIRED_SETUP_STEP_COUNT - currentStep - 1;

  return (
    <PublicRouteShell
      mainLabel="Account setup"
      maxWidth="sm"
      contentClassName="py-4 sm:py-5"
      eyebrow="Account Setup"
      title="Set up FlintTrade"
      subtitle={progressLabel}
    >
      <div className="space-y-4">
        {currentStep > 0 && (
          <div className="flex items-center justify-between gap-3 rounded-xl border border-border-default/70 bg-surface-card/60 px-4 py-2 shadow-xl shadow-black/10 backdrop-blur-xl">
            <p className="text-xs text-text-muted">
              {`${completedCount} of ${REQUIRED_SETUP_STEP_COUNT} completed${remaining > 0 ? ` - ${remaining} remaining` : " - last step"}`}
            </p>
            <Button
              type="button"
              variant="ghost"
              size="xs"
              className="text-text-muted hover:text-text-primary"
              onClick={() => {
                if (
                  window.confirm(
                    "Start over from the beginning? This deletes the unfinished account on this machine so you can begin again.",
                  )
                ) {
                  void handleStartOver();
                }
              }}
            >
              Start over
            </Button>
          </div>
        )}

        <StepIndicator
          total={REQUIRED_SETUP_STEP_COUNT}
          current={currentStep}
          onStepClick={(index) => {
            if (index === 1 && currentStep === 2 && vaultOpened) setCurrentStep(1);
          }}
        />

        <div className="rounded-xl border border-border-default/70 bg-surface-card/70 p-4 shadow-2xl shadow-black/20 backdrop-blur-xl">
          {modeSyncError && currentStep === 2 && (
            <div
              role="alert"
              className="mb-4 flex items-start gap-3 rounded-lg border border-loss/30 bg-loss/10 p-3 text-sm text-loss"
            >
              <AlertTriangle className="size-4 shrink-0 mt-0.5" />
              <span>{modeSyncError}</span>
            </div>
          )}

          {currentStep === 0 && (
            <AccountSecurityStep
              onComplete={handleAccountComplete}
              onBack={handleBack}
              onAccountAlreadyExists={handleAccountAlreadyExists}
            />
          )}

          {currentStep === 1 && (
            <VaultStep
              onOpened={handleVaultOpened}
              onAccountDeleted={handleAccountDeleted}
            />
          )}

          {currentStep === 2 && <PracticeDeskStep />}

          {currentStep === 2 && (
            <div className="flex justify-end mt-6">
              <Button type="button" onClick={() => void handleOpenPractice()}>
                Open Practice desk
              </Button>
            </div>
          )}
        </div>
      </div>
    </PublicRouteShell>
  );
}
