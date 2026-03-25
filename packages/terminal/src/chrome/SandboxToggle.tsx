/**
 * SandboxToggle — TopBar paper / live trading mode switch.
 *
 * - "LIVE" (green) default state
 * - "PAPER" (orange) sandbox state — shows a persistent orange pill in TopBar
 * - Switching to PAPER shows a confirmation dialog
 * - Persists mode in settingsStore (sandboxMode)
 * - Calls POST /ft-api/api/v1/sandbox/config to notify the backend
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
import { useSettingsStore } from "@/stores/settingsStore";
import { toggleSandbox } from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SandboxToggle() {
  const sandboxMode = useSettingsStore((s) => s.sandboxMode);
  const setSandboxMode = useSettingsStore((s) => s.setSandboxMode);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const mutation = useMutation({
    mutationFn: (enabled: boolean) => toggleSandbox(enabled),
    onSuccess: (data) => {
      setSandboxMode(data.enabled);
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
    mutation.mutate(!sandboxMode);
  }, [sandboxMode, mutation]);

  const handleCancel = useCallback(() => {
    setConfirmOpen(false);
  }, []);

  if (sandboxMode) {
    return (
      <>
        <button
          onClick={handleToggle}
          disabled={mutation.isPending}
          aria-label="Paper trading mode active. Click to switch to live trading."
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
                You are about to switch from paper trading to live mode.
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
        aria-label="Live trading mode active. Click to switch to paper trading."
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
            <AlertDialogTitle>Switch to paper trading?</AlertDialogTitle>
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
              Switch to Paper
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
