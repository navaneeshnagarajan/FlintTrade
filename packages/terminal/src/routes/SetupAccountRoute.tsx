/**
 * SetupAccountRoute — one-time account setup wizard (6 steps).
 *
 * Step 1: Account Security  — username, email, password (strength meter), PIN, 2FA TOTP
 * Step 2: Persona           — Trader / Investor / Beginner
 * Step 3: Broker Connection — OpenAlgo host + API key
 * Step 4: Trading Defaults  — exchange, product, quantity
 * Step 5: Risk Limits       — max daily loss, position size
 * Step 6: Mode Selection    — Explore / Practice / Live
 *
 * Session-storage key `flinttrade:setup-progress` persists partial progress so
 * that interrupting after account creation (step 1) and returning does not trigger
 * a duplicate-account error from the backend.
 *
 * On completion navigates to /trade (last used route default).
 */

import { useState, useEffect } from "react";
import { safeParse } from "@/lib/safeParse";
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
  Moon,
  Sun,
  Monitor,
} from "lucide-react";
import { QRCodeSVG } from "qrcode.react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LogoIcon } from "@/components/brand/Logo";
import { StepIndicator } from "@/routes/setup/StepIndicator";
import { PersonaPicker, type Persona } from "@/routes/setup/PersonaStep";
import { ConnectionStep, type ConnectionFormValues } from "@/routes/setup/ConnectionStep";
import { TradingStep, type TradingDefaultsFormValues } from "@/routes/setup/TradingStep";
import { RiskStep, type RiskFormValues } from "@/routes/setup/RiskStep";
import ModeSelectRoute from "@/routes/ModeSelectRoute";
import { useModeStore, type AppMode } from "@/stores/modeStore";
import { useThemeStore } from "@/stores/themeStore";
import type { ColorMode } from "@/lib/cinematicThemes";

// ---------------------------------------------------------------------------
// Session-storage progress tracking
// ---------------------------------------------------------------------------

const PROGRESS_KEY = "flinttrade:setup-progress";

interface SetupProgress {
  accountCreated: boolean;
  totpUri: string;
  backupCodes: string[];
  /** 0 = account security, 1 = persona, 2 = broker, 3 = trading, 4 = risk, 5 = mode */
  completedStep: number;
}

const setupProgressSchema = z.object({
  accountCreated: z.boolean(),
  totpUri: z.string(),
  backupCodes: z.array(z.string()),
  completedStep: z.number().int().min(0).max(5),
}) satisfies z.ZodType<SetupProgress>;

function loadProgress(): SetupProgress | null {
  const raw = sessionStorage.getItem(PROGRESS_KEY);
  return safeParse(raw, setupProgressSchema) ?? null;
}

function saveProgress(progress: SetupProgress): void {
  try {
    sessionStorage.setItem(PROGRESS_KEY, JSON.stringify(progress));
  } catch {
    // Non-critical — ignore storage errors
  }
}

function clearProgress(): void {
  sessionStorage.removeItem(PROGRESS_KEY);
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
    setIsLoading(true);
    setServerError("");
    try {
      const resp = await fetch("/ft-api/v1/auth/setup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: values.username,
          email: values.email,
          password: values.password,
          pin: values.pin || "",
        }),
      });
      const data = await resp.json();
      if (resp.ok && data.data) {
        onComplete(values, data.data.totp_uri ?? "", data.data.backup_codes ?? []);
      } else {
        setServerError(data.message || "Setup failed. Please try again.");
      }
    } catch {
      setServerError("Cannot reach server. Is the FlintTrade backend running?");
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
        <div className="flex items-center gap-2 p-3 rounded-lg bg-loss/10 border border-loss/30 text-sm text-loss">
          <AlertTriangle className="size-4 shrink-0" />
          {serverError}
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
          placeholder="e.g. navaneesh"
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
          ← Back
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
  onBack: () => void;
}

function TotpDisplay({ totpUri, backupCodes, onConfirmed, onBack }: TotpDisplayProps) {
  const [phase, setPhase] = useState<"warning" | "qr">("warning");
  const [downloaded, setDownloaded] = useState(false);
  const [qrVisible, setQrVisible] = useState(false);

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

  // Phase 1: Warning — explain what 2FA is and prompt to get an authenticator app
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

        <div className="flex justify-between items-center mt-6">
          <Button variant="ghost" onClick={onBack} type="button">
            ← Back
          </Button>
          <Button onClick={() => setPhase("qr")}>
            I&apos;m ready — show QR code
          </Button>
        </div>
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
        <Button variant="ghost" onClick={onBack} type="button">
          ← Back
        </Button>
        <Button onClick={onConfirmed}>
          I have saved my codes — Continue
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2: Persona
// ---------------------------------------------------------------------------

interface PersonaStepWrapperProps {
  onComplete: (persona: Persona) => void;
  onBack: () => void;
}

function PersonaStepWrapper({ onComplete, onBack }: PersonaStepWrapperProps) {
  const [selected, setSelected] = useState<Persona | null>(null);

  return (
    <div className="space-y-6">
      <PersonaPicker selected={selected} onSelect={setSelected} />
      <div className="flex justify-between items-center mt-6">
        <Button variant="ghost" onClick={onBack} type="button">
          ← Back
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
  "Persona",
  "Broker Connection",
  "Trading Defaults",
  "Risk Limits",
  "Choose Mode",
];

export default function SetupAccountRoute() {
  const navigate = useNavigate();
  const setMode = useModeStore((s) => s.setMode);
  const colorMode = useThemeStore((s) => s.mode);
  const setColorMode = useThemeStore((s) => s.setMode);

  // ---------------------------------------------------------------------------
  // Restore progress from sessionStorage on mount
  // ---------------------------------------------------------------------------
  const [currentStep, setCurrentStep] = useState(() => {
    const saved = loadProgress();
    if (!saved) return 0;
    // If account was created, start at persona step (or the next incomplete step)
    if (saved.accountCreated) {
      return Math.min(saved.completedStep + 1, STEP_LABELS.length - 1);
    }
    return 0;
  });

  // Saved from Step 1 API response (restored from sessionStorage if available)
  const [totpUri, setTotpUri] = useState(() => loadProgress()?.totpUri ?? "");
  const [backupCodes, setBackupCodes] = useState<string[]>(() => loadProgress()?.backupCodes ?? []);

  // Whether we are showing the TOTP/backup-codes screen (between step 1 and step 2).
  // Restored automatically when accountCreated is true and completedStep is still 0
  // (i.e. the user created the account but hadn't confirmed TOTP yet).
  const [showTotp, setShowTotp] = useState(() => {
    const saved = loadProgress();
    return !!(saved?.accountCreated && saved.completedStep === 0);
  });

  // Keep progress in sync whenever key state changes
  useEffect(() => {
    const saved = loadProgress();
    if (!saved?.accountCreated) return; // nothing to persist yet

    saveProgress({
      accountCreated: true,
      totpUri,
      backupCodes,
      completedStep: currentStep > 0 ? currentStep - 1 : 0,
    });
  }, [currentStep, totpUri, backupCodes]);

  // ---------------------------------------------------------------------------
  // Step handlers
  // ---------------------------------------------------------------------------

  function handleAccountComplete(
    _values: AccountFormValues,
    uri: string,
    codes: string[],
  ) {
    setTotpUri(uri);
    setBackupCodes(codes);
    // Persist immediately so a page reload after account creation goes to TOTP
    saveProgress({ accountCreated: true, totpUri: uri, backupCodes: codes, completedStep: 0 });
    setShowTotp(true);
  }

  function handleTotpConfirmed() {
    setShowTotp(false);
    saveProgress({ accountCreated: true, totpUri, backupCodes, completedStep: 1 });
    setCurrentStep(1);
  }

  function handlePersonaComplete(_persona: Persona) {
    saveProgress({ accountCreated: true, totpUri, backupCodes, completedStep: 2 });
    setCurrentStep(2);
  }

  function handleConnectionComplete(_values: ConnectionFormValues) {
    saveProgress({ accountCreated: true, totpUri, backupCodes, completedStep: 3 });
    setCurrentStep(3);
  }

  function handleTradingComplete(_values: TradingDefaultsFormValues) {
    saveProgress({ accountCreated: true, totpUri, backupCodes, completedStep: 4 });
    setCurrentStep(4);
  }

  function handleRiskComplete(_values: RiskFormValues) {
    saveProgress({ accountCreated: true, totpUri, backupCodes, completedStep: 5 });
    setCurrentStep(5);
  }

  function handleModeSelect(mode: AppMode) {
    setMode(mode);
    // Clear sessionStorage progress on successful completion
    clearProgress();
    // Account is set up. Navigate to /welcome which will detect
    // the account exists (status = "logged-out") and immediately
    // show the login form — skipping the cinematic + "Get Started" CTA.
    // The user logs in with the credentials they just created.
    navigate("/welcome", { replace: true });
  }

  // ---------------------------------------------------------------------------
  // Back navigation
  // ---------------------------------------------------------------------------

  function handleBack() {
    if (showTotp) {
      // Back from TOTP warning/QR screen returns to the account form view.
      // The account IS already created on the backend — we just return to
      // the TOTP display so the user doesn't re-submit the form.
      setShowTotp(false);
      return;
    }
    if (currentStep === 0) {
      navigate("/welcome");
      return;
    }
    setCurrentStep((s) => s - 1);
  }

  const totalSteps = STEP_LABELS.length;

  return (
    <main aria-label="Account setup" className="min-h-screen bg-surface-base flex flex-col items-center justify-center p-6 relative">

      {/* Dark / light / system mode toggle — top-right */}
      <div className="absolute top-4 right-4 flex gap-1 z-50">
        {(["dark", "light", "system"] as const).map((m) => {
          const Icon = m === "dark" ? Moon : m === "light" ? Sun : Monitor;
          return (
            <button
              key={m}
              onClick={() => setColorMode(m as ColorMode)}
              aria-label={`${m} mode`}
              className={`p-1.5 rounded transition-colors focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
                colorMode === m ? "bg-accent/20 text-accent" : "text-text-muted hover:text-text-primary"
              }`}
            >
              <Icon size={14} />
            </button>
          );
        })}
      </div>

      <div className="w-full max-w-lg space-y-8">

        {/* Header */}
        <div className="flex flex-col items-center gap-3 text-center">
          <LogoIcon size={36} />
          <div>
            <h1 className="font-heading font-bold text-xl text-text-primary">
              Set up FlintTrade
            </h1>
            <p className="text-xs text-text-muted mt-0.5">
              Step {currentStep + 1} of {totalSteps} — {STEP_LABELS[currentStep]}
            </p>
          </div>
        </div>

        {/* Step indicator */}
        <StepIndicator
          total={totalSteps}
          current={currentStep}
          onStepClick={(i) => {
            // Allow navigating back to completed steps only
            if (i < currentStep) setCurrentStep(i);
          }}
        />

        {/* Step content — step 5 (ModeSelect) renders its own full layout */}
        {currentStep === 5 ? (
          <ModeSelectRoute onSelect={handleModeSelect} />
        ) : (
          <div className="rounded-xl border border-border-default bg-surface-card p-6">
            {currentStep === 0 && !showTotp && (
              <AccountSecurityStep
                onComplete={handleAccountComplete}
                onBack={handleBack}
              />
            )}

            {currentStep === 0 && showTotp && (
              <TotpDisplay
                totpUri={totpUri}
                backupCodes={backupCodes}
                onConfirmed={handleTotpConfirmed}
                onBack={handleBack}
              />
            )}

            {currentStep === 1 && (
              <PersonaStepWrapper
                onComplete={handlePersonaComplete}
                onBack={handleBack}
              />
            )}

            {currentStep === 2 && (
              <ConnectionStep
                onComplete={handleConnectionComplete}
              />
            )}

            {currentStep === 3 && (
              <TradingStep
                onComplete={handleTradingComplete}
              />
            )}

            {currentStep === 4 && (
              <RiskStep
                onComplete={handleRiskComplete}
              />
            )}
          </div>
        )}

        {/* Back button for steps 2–4 that use their own sub-components
            (ConnectionStep, TradingStep, RiskStep render their own submit buttons) */}
        {currentStep >= 2 && currentStep <= 4 && (
          <div className="flex justify-start">
            <Button variant="ghost" onClick={handleBack} type="button">
              ← Back
            </Button>
          </div>
        )}
      </div>
    </main>
  );
}
