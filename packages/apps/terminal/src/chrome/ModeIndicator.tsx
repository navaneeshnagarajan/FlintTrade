/**
 * ModeIndicator — TopBar mode menu.
 *
 * The chip opens a menu of Practice, Connected (read), and Live.
 * Connected (read) stays disabled until a broker is connected.
 * Live stays disabled while any lock reason applies: missing 2FA or broker,
 * and, when the place gate reports it, Laya qualification.
 * Opening the menu never opens the Live dialog. The PIN unlock runs only
 * after the operator chooses an eligible Live item.
 */

import { useCallback, useEffect, useState } from "react";
import { Eye, FlaskConical, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useTotpEnrolled } from "@/hooks/useTotpEnrolled";
import { downgradeMode, unlockWithPin } from "@/lib/modeAuth";
import {
  ENROL_2FA_AND_CONNECT_BROKER,
  liveMenuLockReasons,
} from "@/chrome/liveLockReasons";
import { setConnectedReadPosture } from "@/lib/operatorModeLabel";

export const CONNECT_BROKER_FIRST = "Connect a broker first";
export const LIVE_LOCKED_REASON = ENROL_2FA_AND_CONNECT_BROKER;

export interface ModeIndicatorProps {
  /**
   * Laya Live qualification, when the place gate reports it.
   * Omit this while that status does not exist. `false` adds
   * "Not qualified for Live" to the disabled Live reasons.
   */
  layaQualifiedForLive?: boolean;
}

const CHIP_CLASS = {
  practice:
    "h-7 gap-1 px-2.5 rounded text-xs font-medium font-heading bg-amber-500/15 text-amber-400 border border-amber-500/30 hover:bg-amber-500/25 hover:text-amber-400",
  connectedRead:
    "h-7 gap-1 px-2.5 rounded text-xs font-medium font-heading bg-sky-500/15 text-sky-300 border border-sky-500/30 hover:bg-sky-500/25 hover:text-sky-300",
  live:
    "h-7 gap-1 px-2.5 rounded text-xs font-medium font-heading bg-profit/20 text-profit border border-profit/40 hover:bg-profit/30 hover:text-profit",
} as const;

export default function ModeIndicator({ layaQualifiedForLive }: ModeIndicatorProps = {}) {
  const mode = useModeStore((s) => s.mode);
  const setMode = useModeStore((s) => s.setMode);
  const token = useAuthStore((s) => s.token);
  const updateToken = useAuthStore((s) => s.updateToken);
  const brokerConnected = useBrokerConnected();
  const totpEnrolled = useTotpEnrolled();
  const liveReasons = liveMenuLockReasons({
    brokerConnected,
    totpEnrolled,
    layaQualifiedForLive,
  });
  const liveEligible = liveReasons.length === 0;

  const [readPosture, setReadPosture] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pin, setPin] = useState("");
  const [pinError, setPinError] = useState("");
  const [toggleError, setToggleError] = useState("");

  const showConnectedRead = readPosture && brokerConnected && mode !== "live";
  const chipLabel = mode === "live" ? "Live" : showConnectedRead ? "Connected (read)" : "Practice";

  useEffect(() => {
    setConnectedReadPosture(showConnectedRead);
    return () => setConnectedReadPosture(false);
  }, [showConnectedRead]);
  const chipClass = mode === "live"
    ? CHIP_CLASS.live
    : showConnectedRead
      ? CHIP_CLASS.connectedRead
      : CHIP_CLASS.practice;

  const switchToPractice = useCallback(async () => {
    setToggleError("");
    if (token === "demo-user") {
      window.dispatchEvent(
        new CustomEvent("flinttrade:navigate", { detail: { path: "/setup" } }),
      );
      return false;
    }
    if (mode === "practice") return true;
    try {
      const authState = useAuthStore.getState();
      const newToken = await downgradeMode("practice", authState.token);
      if (!updateToken(newToken, authState.sessionGeneration)) return false;
    } catch {
      setToggleError(
        mode === "live"
          ? "Could not downgrade to Practice — try again."
          : "Could not switch to Practice — try again.",
      );
      return false;
    }
    setMode("practice");
    return true;
  }, [mode, setMode, token, updateToken]);

  const selectPractice = useCallback(async () => {
    setReadPosture(false);
    await switchToPractice();
  }, [switchToPractice]);

  const selectConnectedRead = useCallback(async () => {
    if (!brokerConnected) return;
    const switched = mode === "practice" ? true : await switchToPractice();
    if (switched) setReadPosture(true);
  }, [brokerConnected, mode, switchToPractice]);

  const selectLive = useCallback(() => {
    if (!liveEligible || mode === "live") return;
    setPin("");
    setPinError("");
    setConfirmOpen(true);
  }, [liveEligible, mode]);

  const handleConfirmLive = useCallback(async () => {
    if (pin.length !== 6 || /\D/.test(pin)) {
      setPinError("Enter your 6-digit PIN.");
      return;
    }
    try {
      const expectedGeneration = useAuthStore.getState().sessionGeneration;
      const { token: newToken } = await unlockWithPin(pin, "live");
      if (!updateToken(newToken, expectedGeneration)) return;
    } catch (err) {
      const message = err instanceof Error ? err.message.trim() : "";
      setPinError(message || "Incorrect PIN. Try again.");
      return;
    }
    setPinError("");
    setConfirmOpen(false);
    setReadPosture(false);
    setMode("live");
  }, [pin, setMode, updateToken]);

  const handleCancel = useCallback(() => {
    setConfirmOpen(false);
    setPin("");
    setPinError("");
  }, []);

  const ChipIcon = mode === "live" ? Zap : showConnectedRead ? Eye : FlaskConical;

  return (
    <div className="flex items-center gap-2">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            data-testid="execution-mode"
            aria-label={`${chipLabel} mode. Open the mode menu.`}
            className={chipClass}
          >
            <ChipIcon size={11} aria-hidden="true" />
            {chipLabel}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" aria-label="Mode" className="w-64">
          <DropdownMenuItem onSelect={() => { void selectPractice(); }}>
            Practice
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={!brokerConnected}
            onSelect={() => { void selectConnectedRead(); }}
          >
            <span className="flex flex-col items-start gap-0.5">
              <span>Connected (read)</span>
              {!brokerConnected ? (
                <span className="text-xxs text-text-muted">{CONNECT_BROKER_FIRST}</span>
              ) : null}
            </span>
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={!liveEligible}
            onSelect={selectLive}
          >
            <span className="flex flex-col items-start gap-0.5">
              <span>Live</span>
              {liveReasons.length > 0 ? (
                <span
                  data-testid="live-lock-reasons"
                  className="flex flex-col items-start gap-0.5 text-xxs text-text-muted"
                >
                  {liveReasons.map((reason) => (
                    <span key={reason}>{reason}</span>
                  ))}
                </span>
              ) : null}
            </span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {toggleError ? (
        <span role="alert" className="text-xs text-loss">
          {toggleError}
        </span>
      ) : null}

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Switch to Live Trading?</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-3">
                <p>
                  You are about to switch to <strong>Live mode</strong>. All
                  orders will be executed with <strong>real money</strong>{" "}
                  through your broker.
                </p>
                <div>
                  <label
                    htmlFor="mode-pin"
                    className="text-xs font-medium text-text-secondary block mb-1.5"
                  >
                    Enter your PIN to confirm
                  </label>
                  <Input
                    id="mode-pin"
                    type="password"
                    inputMode="numeric"
                    maxLength={6}
                    value={pin}
                    onChange={(e) => {
                      setPin(e.target.value.replace(/\D/g, ""));
                      if (pinError) setPinError("");
                    }}
                    placeholder="6-digit PIN"
                    className="text-center font-mono text-lg tracking-widest max-w-40"
                    onKeyDown={(e) => e.key === "Enter" && void handleConfirmLive()}
                    autoFocus
                  />
                  {pinError ? (
                    <p className="text-xs text-loss mt-1">{pinError}</p>
                  ) : null}
                </div>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={handleCancel}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                void handleConfirmLive();
              }}
              disabled={pin.length !== 6}
              className="bg-profit hover:bg-profit/90 text-white"
            >
              Switch to Live
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
