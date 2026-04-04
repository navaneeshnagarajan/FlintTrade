/**
 * SandboxToggle — TopBar paper / live trading mode switch.
 *
 * - "PAPER" (amber) displayed when mode === "practice"
 * - "LIVE" (green) displayed when mode === "live"
 * - Both directions require confirmation before switching
 * - Calls POST /ft-api/api/v1/sandbox/config to notify the backend
 * - Mode is now owned exclusively by modeStore — settingsStore no longer
 *   holds a sandboxMode flag.
 */

import { useState, useCallback } from "react";
import { FlaskConical } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
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
import { useModeStore } from "@/stores/modeStore";
import { toggleSandbox } from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SandboxToggle() {
  const mode = useModeStore((s) => s.mode);
  const setMode = useModeStore((s) => s.setMode);
  const isPractice = mode === "practice";
  const [confirmOpen, setConfirmOpen] = useState(false);

  const mutation = useMutation({
    mutationFn: (enabled: boolean) => toggleSandbox(enabled),
    onSuccess: (data) => {
      // Sync the backend's response back into the mode store
      setMode(data.enabled ? "practice" : "live");
    },
    onError: () => {
      // Revert optimistic state on error — do nothing, state stays as-is
    },
  });

  const handleToggle = useCallback(() => {
    // Both directions require confirmation — switching to live can cause real orders
    setConfirmOpen(true);
  }, []);

  const handleConfirm = useCallback(() => {
    setConfirmOpen(false);
    mutation.mutate(!isPractice);
  }, [isPractice, mutation]);

  const handleCancel = useCallback(() => {
    setConfirmOpen(false);
  }, []);

  // Only render this toggle when the user is in practice or live mode.
  // In explore mode the ModePill already handles mode switching.
  if (mode === "explore") return null;

  if (isPractice) {
    return (
      <>
        <button
          onClick={handleToggle}
          disabled={mutation.isPending}
          aria-label="Practice trading mode active. Click to switch to live trading."
          className="flex items-center gap-1 h-7 px-2 rounded text-xs font-medium bg-amber-500/15 text-amber-400 border border-amber-500/30 hover:bg-amber-500/25 transition-colors"
        >
          <FlaskConical size={11} aria-hidden="true" />
          PAPER
        </button>

        <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Switch to Live Trading?</AlertDialogTitle>
              <AlertDialogDescription>
                You are about to switch from practice trading to live mode.
                All orders will be executed with real money.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel onClick={handleCancel}>Cancel</AlertDialogCancel>
              <AlertDialogAction onClick={handleConfirm}>Switch to Live</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </>
    );
  }

  return (
    <>
      <button
        onClick={handleToggle}
        disabled={mutation.isPending}
        aria-label="Live trading mode active. Click to switch to practice trading."
        className="flex items-center gap-1 h-7 px-2 rounded text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
      >
        <span
          className="w-1.5 h-1.5 rounded-full bg-profit shrink-0"
          aria-hidden="true"
        />
        LIVE
      </button>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Switch to practice trading?</AlertDialogTitle>
            <AlertDialogDescription>
              Orders will be simulated and will not be sent to your broker.
              All order amounts and P&amp;L will be virtual. You can switch back
              to live trading at any time.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={handleCancel}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirm}
              className="bg-amber-500 hover:bg-amber-600 text-white"
            >
              Switch to Practice
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
