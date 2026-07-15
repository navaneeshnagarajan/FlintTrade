/**
 * RiskSection — local MTM references and account-bound backend L4 controls.
 *
 * Local reference values remain in Zustand. Percentage daily-loss thresholds,
 * opening capital, and latch resets use the authoritative backend.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { RefreshCw, Save, CheckCircle2, AlertTriangle, RotateCcw, LockKeyhole } from "lucide-react";
import { FieldRow, TextInput, SectionTitle } from "./shared";
import { Button } from "@/components/ui/button";
import { RISK_HINTS } from "@/lib/schemas/riskSchema";
import {
  getSafetyConfigForTarget,
  resetDailyPnLState,
  updateSafetyConfig,
  type SafetyAccountTarget,
  type SafetyConfig,
} from "@/services/ftApi";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { brokerAccountKey, findBrokerAccountMatch, useBrokerStore } from "@/stores/brokerStore";
import { pickNativeBrokerOrderTargetFromState } from "@/services/brokerTargets";

export interface RiskSettings {
  maxPositionLots: string;
  mtmStoploss: string;
  mtmTarget: string;
  maxOrdersPerMinute: string;
}

interface RiskSectionProps {
  settings: RiskSettings;
  onChange: (field: keyof RiskSettings, value: string) => void;
}

const SAFETY_CONFIG_QUERY_KEY = "safetyConfig";

export function buildRiskSafetyConfigUpdate(
  dailyLossPausePct: string,
  dailyLossHardStopPct: string,
): Partial<SafetyConfig> {
  const pausePct = Number(dailyLossPausePct);
  const hardStopPct = Number(dailyLossHardStopPct);
  if (!Number.isFinite(pausePct) || pausePct <= 0) {
    throw new Error("Daily-loss pause threshold must be a positive number");
  }
  if (!Number.isFinite(hardStopPct) || hardStopPct <= pausePct) {
    throw new Error("Daily-loss hard stop must be greater than the positive pause threshold");
  }
  return {
    daily_loss_pause_pct: pausePct,
    daily_loss_kill_pct: hardStopPct,
  };
}

export function RiskSection({ settings, onChange }: RiskSectionProps) {
  const mode = useModeStore((state) => state.mode);
  const isLive = mode === "live";
  const apiKey = useConnectionStore((state) => state.apiKey);
  const openAlgoHydrated = useConnectionStore((state) => state.openAlgoHydrated);
  const accounts = useBrokerStore((state) => state.accounts);
  const activeAccountId = useBrokerStore((state) => state.activeAccountId);
  const activeAccount = useMemo(
    () => findBrokerAccountMatch(accounts, activeAccountId),
    [accounts, activeAccountId],
  );
  const safetyTarget = useMemo<SafetyAccountTarget | undefined>(() => {
    if (!isLive || !openAlgoHydrated) return undefined;
    if (apiKey.trim()) return { broker: "openalgo", account_id: "default" };
    return pickNativeBrokerOrderTargetFromState(
      mode,
      apiKey,
      accounts,
      activeAccountId,
      openAlgoHydrated,
    );
  }, [accounts, activeAccountId, apiKey, isLive, mode, openAlgoHydrated]);
  const backendSelectorKey = safetyTarget
    ? `${safetyTarget.broker}:${safetyTarget.account_id}`
    : "unbound";
  const displayedSelectorKey = safetyTarget
    ? apiKey.trim()
      ? "gateway:openalgo:default"
      : activeAccount
        ? brokerAccountKey(activeAccount)
        : `native:${safetyTarget.broker}:${safetyTarget.account_id}`
    : "unbound";
  const [feedback, setFeedback] = useState<{ variant: "success" | "error"; message: string } | null>(null);
  const [dailyLossPausePct, setDailyLossPausePct] = useState("");
  const [dailyLossHardStopPct, setDailyLossHardStopPct] = useState("");
  const [openingRiskCapital, setOpeningRiskCapital] = useState("");
  const hydratedSelector = useRef<string | null>(null);
  const safetyQuery = useQuery({
    queryKey: [SAFETY_CONFIG_QUERY_KEY, "risk", displayedSelectorKey],
    queryFn: () => {
      if (!safetyTarget) throw new Error("No execution account is selected");
      return getSafetyConfigForTarget(safetyTarget);
    },
    enabled: isLive && safetyTarget !== undefined,
  });

  useEffect(() => {
    if (!safetyQuery.data || hydratedSelector.current === displayedSelectorKey) return;
    setDailyLossPausePct(String(safetyQuery.data.daily_loss_pause_pct));
    setDailyLossHardStopPct(String(safetyQuery.data.daily_loss_kill_pct));
    setOpeningRiskCapital(
      safetyQuery.data.opening_risk_capital
        ? String(safetyQuery.data.opening_risk_capital)
        : "",
    );
    hydratedSelector.current = displayedSelectorKey;
    setFeedback(null);
  }, [displayedSelectorKey, safetyQuery.data]);

  const selectorMatches = safetyQuery.data?.daily_loss_selector === backendSelectorKey;
  const accountStateReady = isLive
    && safetyTarget !== undefined
    && selectorMatches
    && !safetyQuery.isLoading
    && !safetyQuery.isError;

  function showSuccess(message: string) {
    setFeedback({ variant: "success", message });
  }

  function showError(error: unknown, fallback: string) {
    setFeedback({
      variant: "error",
      message: error instanceof Error && error.message ? error.message : fallback,
    });
  }

  const syncMutation = useMutation({
    mutationFn: () => updateSafetyConfig(
      buildRiskSafetyConfigUpdate(
        dailyLossPausePct,
        dailyLossHardStopPct,
      ),
    ),
    onSuccess: () => {
      showSuccess("Backend daily-loss limits updated");
    },
    onError: (error) => {
      showError(error, "Failed to update backend daily-loss limits");
    },
  });

  const capitalMutation = useMutation({
    mutationFn: ({
      capital,
      target,
    }: {
      capital: number;
      target: SafetyAccountTarget;
    }) => {
      if (!Number.isFinite(capital) || capital <= 0) {
        throw new Error("Opening risk capital must be positive");
      }
      return updateSafetyConfig({ opening_risk_capital: capital }, target);
    },
    onSuccess: (_result, { target }) => {
      showSuccess(`Opening risk capital frozen for ${target.broker}:${target.account_id}`);
      void safetyQuery.refetch();
    },
    onError: (error) => {
      showError(error, "Failed to freeze opening risk capital");
    },
  });

  const resetMutation = useMutation({
    mutationFn: (target: SafetyAccountTarget) => resetDailyPnLState(target),
    onSuccess: (_result, target) => {
      showSuccess(`Daily-loss stop reset for ${target.broker}:${target.account_id}`);
      void safetyQuery.refetch();
    },
    onError: (error) => {
      showError(error, "Failed to reset daily-loss stop");
    },
  });

  function handleSync() {
    setFeedback(null);
    syncMutation.mutate();
  }

  function handleFreezeCapital() {
    setFeedback(null);
    if (!safetyTarget || !accountStateReady) {
      showError(undefined, "The displayed execution account is not ready for a safety update");
      return;
    }
    capitalMutation.mutate({
      capital: Number(openingRiskCapital),
      target: safetyTarget,
    });
  }

  function handleReset() {
    setFeedback(null);
    if (!safetyTarget || !accountStateReady) {
      showError(undefined, "The displayed execution account is not ready for a safety reset");
      return;
    }
    resetMutation.mutate(safetyTarget);
  }

  return (
    <div className="space-y-5">
      <SectionTitle>Risk Limits</SectionTitle>

      <div className="p-3 rounded bg-warning/5 border border-warning/20 text-xs text-warning/80">
        Rupee MTM and lot/rate references are local display preferences. Percentage daily-loss
        values are backend new-order stops. Only the explicit Layer 5 Kill Switch attempts cancel
        and flatten actions.
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-border-default bg-surface-base px-3 py-2 text-xs">
        <span className="text-text-muted">Daily-loss account</span>
        {safetyTarget ? (
          <code className="font-mono text-text-primary">{displayedSelectorKey}</code>
        ) : (
          <span className="text-warning">No connected execution account selected</span>
        )}
      </div>

      {safetyQuery.isError && (
        <p role="alert" className="text-xs text-loss">
          {safetyQuery.error instanceof Error && safetyQuery.error.message
            ? safetyQuery.error.message
            : "Failed to load account-bound daily-loss state"}
        </p>
      )}

      <FieldRow
        label="Position Lot Reference"
        hint="Stored locally for reference. Position rows are not currently converted to lots."
      >
        <TextInput
          value={settings.maxPositionLots}
          onChange={(v) => onChange("maxPositionLots", v)}
          placeholder="e.g. 10"
          type="number"
          aria-label="Position lot reference"
        />
      </FieldRow>

      <FieldRow
        label="MTM Stop-loss (INR)"
        hint="Local MTM alert and manual kill-switch prompt threshold. This value does not auto-flatten positions."
        tooltip={RISK_HINTS.mtmStoploss}
      >
        <TextInput
          value={settings.mtmStoploss}
          onChange={(v) => onChange("mtmStoploss", v)}
          placeholder="e.g. 5000"
          type="number"
          aria-label="MTM stoploss in INR"
        />
      </FieldRow>

      <FieldRow
        label="MTM Target (INR)"
        hint="Local MTM profit target used by terminal monitors. It does not activate Layer 5."
        tooltip={RISK_HINTS.mtmTarget}
      >
        <TextInput
          value={settings.mtmTarget}
          onChange={(v) => onChange("mtmTarget", v)}
          placeholder="e.g. 10000"
          type="number"
          aria-label="MTM profit target in INR"
        />
      </FieldRow>

      <FieldRow
        label="Opening Risk Capital (INR)"
        hint="Frozen for the displayed account and trading date. Required before account daily-loss checks can admit orders."
      >
        <div className="flex flex-wrap items-center gap-2">
          <TextInput
            value={openingRiskCapital}
            onChange={setOpeningRiskCapital}
            placeholder="e.g. 100000"
            type="number"
            disabled={!accountStateReady || Boolean(safetyQuery.data?.opening_risk_capital)}
            aria-label="Opening risk capital in INR"
          />
          <Button
            variant="outline"
            size="sm"
            onClick={handleFreezeCapital}
            disabled={
              !accountStateReady
              || capitalMutation.isPending
              || Boolean(safetyQuery.data?.opening_risk_capital)
              || !(Number(openingRiskCapital) > 0)
            }
            className="h-7 shrink-0 gap-1.5 text-xs"
          >
            <LockKeyhole size={11} />
            Freeze
          </Button>
        </div>
      </FieldRow>

      <FieldRow
        label="Daily-Loss Pause (%)"
        hint="Blocks subsequent new orders after this percentage loss until the pause is reset."
      >
        <TextInput
          value={dailyLossPausePct}
          onChange={setDailyLossPausePct}
          placeholder="e.g. 3"
          type="number"
          disabled={!accountStateReady}
          aria-label="Daily loss pause threshold in percent"
        />
      </FieldRow>

      <FieldRow
        label="Daily-Loss Hard Stop (%)"
        hint="Latches a new-order hard stop until manual reset. It does not cancel orders or flatten positions."
      >
        <TextInput
          value={dailyLossHardStopPct}
          onChange={setDailyLossHardStopPct}
          placeholder="e.g. 15"
          type="number"
          disabled={!accountStateReady}
          aria-label="Daily loss hard stop threshold in percent"
        />
      </FieldRow>

      <FieldRow
        label="Order-Rate Reference (/min)"
        hint="Stored locally for reference. The terminal does not currently measure a rolling order-placement rate."
      >
        <TextInput
          value={settings.maxOrdersPerMinute}
          onChange={(v) => onChange("maxOrdersPerMinute", v)}
          placeholder="e.g. 20"
          type="number"
          aria-label="Order-rate reference per minute"
        />
      </FieldRow>

      {/* Sync to backend button */}
      <div className="flex flex-wrap items-center gap-3 pt-1">
        <Button
          variant="outline"
          size="sm"
          onClick={handleSync}
          disabled={!accountStateReady || syncMutation.isPending}
          className="flex items-center gap-1.5 text-xs h-7"
        >
          {syncMutation.isPending ? (
            <RefreshCw size={11} className="animate-spin" />
          ) : (
            <Save size={11} />
          )}
          {syncMutation.isPending ? "Syncing..." : "Sync Backend Daily-Loss Limits"}
        </Button>

        {feedback && (
          <span
            role={feedback.variant === "error" ? "alert" : "status"}
            aria-live={feedback.variant === "error" ? "assertive" : "polite"}
            aria-atomic="true"
            className={[
              "flex items-center gap-1 text-xs",
              feedback.variant === "error" ? "text-loss" : "text-profit",
            ].join(" ")}
          >
            {feedback.variant === "error"
              ? <AlertTriangle size={11} />
              : <CheckCircle2 size={11} />}
            {feedback.message}
          </span>
        )}
        {(safetyQuery.data?.daily_loss_pause_active
          || safetyQuery.data?.daily_loss_hard_stop_active) && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleReset}
            disabled={!accountStateReady || resetMutation.isPending}
            className="ml-auto flex items-center gap-1.5 text-xs h-7"
          >
            <RotateCcw size={11} className={resetMutation.isPending ? "animate-spin" : ""} />
            Reset Daily-Loss Stop
          </Button>
        )}
      </div>
    </div>
  );
}
