/**
 * SafetyControls — process-wide kill switch and global backend risk caps.
 */

import { useState, useEffect, useCallback } from "react";
import {
  Loader2, ShieldAlert, ShieldCheck, AlertTriangle, CheckCircle2,
} from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { GlassCard } from "@/components/ui/GlassCard";
import { StaggeredList } from "@/components/motion/StaggeredList";
import {
  getSafetyConfig,
  updateSafetyConfig,
  activateKillSwitch,
  resetKillSwitch,
  type SafetyConfig,
} from "@/services/ftApi";
import { emitNotification } from "@/components/NotificationCentre/useNotificationFeed";
import { useModeStore } from "@/stores/modeStore";

const SAFETY_CONFIG_QUERY_KEY = ["safetyConfig"] as const;

const GLOBAL_CAP_FIELDS = [
  "max_positions",
  "max_margin_pct",
  "max_net_delta",
  "max_net_vega",
] as const satisfies ReadonlyArray<keyof SafetyConfig>;

type GlobalCapField = (typeof GLOBAL_CAP_FIELDS)[number];

export function buildGlobalCapUpdate(
  config: Partial<SafetyConfig>,
): Partial<SafetyConfig> {
  return Object.fromEntries(
    GLOBAL_CAP_FIELDS.flatMap((key) => (
      config[key] === undefined ? [] : [[key, config[key]]]
    )),
  ) as Partial<SafetyConfig>;
}

function SafetyFeedback({
  message,
  variant,
  onDismiss,
}: {
  message: string;
  variant: "success" | "error";
  onDismiss: () => void;
}) {
  useEffect(() => {
    const id = setTimeout(onDismiss, 3000);
    return () => clearTimeout(id);
  }, [onDismiss]);

  return (
    <div
      role={variant === "error" ? "alert" : "status"}
      aria-live={variant === "error" ? "assertive" : "polite"}
      aria-atomic="true"
      className={`flex items-center gap-2 rounded border px-3 py-2 text-xs ${
        variant === "error" ? "bg-loss/10 border-loss/20 text-loss" : "bg-profit/10 border-profit/20 text-profit"
      }`}
    >
      {variant === "error" ? <AlertTriangle size={13} /> : <CheckCircle2 size={13} />}
      <span>{message}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main section
// ---------------------------------------------------------------------------

export function SafetyControls() {
  const queryClient = useQueryClient();
  const mode = useModeStore((state) => state.mode);
  const isLive = mode === "live";
  const [killReason, setKillReason]   = useState("");
  const [toast, setToast]             = useState<{ msg: string; variant: "success" | "error" } | null>(null);
  const dismissToast                  = useCallback(() => setToast(null), []);
  const [localConfig, setLocalConfig] = useState<Partial<SafetyConfig>>({});
  const [configDirty, setConfigDirty] = useState(false);

  const {
    data: safetyConfig,
    isLoading: loadingConfig,
    isError: configError,
  } = useQuery({
    queryKey: SAFETY_CONFIG_QUERY_KEY,
    queryFn: getSafetyConfig,
    refetchInterval: 5_000,
  });

  useEffect(() => {
    if (safetyConfig && !configDirty) setLocalConfig(safetyConfig);
  }, [safetyConfig, configDirty]);

  const updateConfigMutation = useMutation({
    mutationFn: (cfg: Partial<SafetyConfig>) => updateSafetyConfig(
      buildGlobalCapUpdate(cfg),
    ),
    onMutate: () => queryClient.cancelQueries({ queryKey: SAFETY_CONFIG_QUERY_KEY, exact: true }),
    onSuccess: (_result, cfg) => {
      queryClient.setQueryData<SafetyConfig>(SAFETY_CONFIG_QUERY_KEY, (current) => current
        ? { ...current, ...buildGlobalCapUpdate(cfg) }
        : current);
      setConfigDirty(false);
      void queryClient.invalidateQueries({ queryKey: SAFETY_CONFIG_QUERY_KEY });
      setToast({ msg: "Safety config saved", variant: "success" });
    },
    onError: (err: Error) => {
      setToast({ msg: err.message ?? "Failed to save config", variant: "error" });
    },
  });

  const activateKillMutation = useMutation({
    mutationFn: (reason: string) => activateKillSwitch(reason),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: SAFETY_CONFIG_QUERY_KEY });
      const current = queryClient.getQueryData<SafetyConfig>(SAFETY_CONFIG_QUERY_KEY);
      if (current === undefined) {
        throw new Error("Authoritative safety state is unavailable");
      }
      return { safetyConfig: current };
    },
    onSuccess: (result, _reason, context) => {
      const flattenComplete = result.emergency_actions.complete;
      const current = queryClient.getQueryData<SafetyConfig>(SAFETY_CONFIG_QUERY_KEY) ?? context.safetyConfig;
      queryClient.setQueryData<SafetyConfig>(SAFETY_CONFIG_QUERY_KEY, {
        ...current,
        kill_switch_active: result.is_active,
        kill_switch_reason: result.reason,
        flatten_complete: flattenComplete,
        emergency_result: result.emergency_actions,
      });
      setToast({
        msg: flattenComplete
          ? "Kill switch activated; emergency broker actions completed"
          : "Kill switch is active, but broker flattening is incomplete",
        variant: flattenComplete ? "success" : "error",
      });
      setKillReason("");
      emitNotification({
        category: "system",
        title: "Kill switch ACTIVATED",
        body: flattenComplete
          ? "All live order routing is halted and emergency broker actions completed."
          : "Live order routing is halted, but one or more broker flattening actions did not complete. Review broker state before resetting.",
      });
    },
    onError: (err: Error) => {
      setToast({ msg: err.message ?? "Failed to activate kill switch", variant: "error" });
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: SAFETY_CONFIG_QUERY_KEY,
        refetchType: "active",
      });
    },
  });

  const resetKillMutation = useMutation({
    mutationFn: () => resetKillSwitch(),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: SAFETY_CONFIG_QUERY_KEY });
    },
    onSuccess: () => {
      queryClient.setQueryData<SafetyConfig>(SAFETY_CONFIG_QUERY_KEY, (current) => current
        ? {
            ...current,
            kill_switch_active: false,
            kill_switch_reason: "",
            flatten_complete: true,
            emergency_result: null,
          }
        : current);
      setToast({ msg: "Kill switch reset — live order routing resumed", variant: "success" });
      emitNotification({
        category: "system",
        title: "Kill switch reset",
        body: "Order routing has resumed.",
      });
    },
    onError: (err: Error) => {
      setToast({ msg: err.message ?? "Failed to reset kill switch", variant: "error" });
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: SAFETY_CONFIG_QUERY_KEY,
        refetchType: "active",
      });
    },
  });

  const killSwitchState = safetyConfig === undefined
    ? loadingConfig ? "loading" : "unknown"
    : safetyConfig.kill_switch_active ? "active" : "inactive";
  const killSwitchActive = killSwitchState === "active";
  const flattenComplete = killSwitchActive && safetyConfig?.flatten_complete === true;

  const updateField = <K extends keyof SafetyConfig>(key: K, value: SafetyConfig[K]) => {
    setLocalConfig((prev) => ({ ...prev, [key]: value }));
    setConfigDirty(true);
  };

  const numericField = (label: string, key: GlobalCapField, unit?: string) => {
    const raw    = localConfig[key];
    const numVal = typeof raw === "number" ? raw : 0;
    const inputId = `settings-safety-${key}`;
    return (
      <div className="space-y-1">
        <label htmlFor={inputId} className="text-xs text-text-muted">{label}</label>
        <div className="flex items-center gap-1.5">
          <Input
            id={inputId}
            type="number"
            value={numVal}
            onChange={(e) => updateField(key, Number(e.target.value) as SafetyConfig[typeof key])}
            disabled={!isLive || updateConfigMutation.isPending}
            className="h-8 text-xs bg-surface-base border-border-default text-text-primary w-28"
          />
          {unit && <span className="text-xs text-text-muted">{unit}</span>}
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {toast && <SafetyFeedback message={toast.msg} variant={toast.variant} onDismiss={dismissToast} />}

      <StaggeredList className="space-y-4">

        {/* Kill Switch */}
        <GlassCard className="p-6">
          <div className="flex items-center gap-2 mb-1">
            {killSwitchState === "active" ? (
              <>
                <span className="h-2 w-2 shrink-0 rounded-full bg-loss" />
                <ShieldAlert size={18} className="text-loss" />
              </>
            ) : killSwitchState === "inactive" ? (
              <>
                <span className="h-2 w-2 shrink-0 rounded-full bg-profit" />
                <ShieldCheck size={18} className="text-profit" />
              </>
            ) : killSwitchState === "loading" ? (
              <Loader2 size={18} className="animate-spin text-text-muted" />
            ) : (
              <AlertTriangle size={18} className="text-warning" />
            )}
            <h3 className="font-heading font-semibold text-lg text-text-primary">Kill Switch</h3>
            {killSwitchState === "active" && (
              <Badge className="ml-auto text-xs bg-loss/10 text-loss border-0">ACTIVE</Badge>
            )}
            {killSwitchState === "inactive" && (
              <Badge className="ml-auto text-xs bg-profit/10 text-profit border-0">INACTIVE</Badge>
            )}
            {killSwitchState === "loading" && (
              <Badge className="ml-auto text-xs bg-text-muted/10 text-text-muted border-0">LOADING</Badge>
            )}
            {killSwitchState === "unknown" && (
              <Badge className="ml-auto text-xs bg-warning/10 text-warning border-0">UNKNOWN</Badge>
            )}
          </div>
          <p className="text-sm text-text-secondary mb-4 leading-relaxed">
            Process-wide emergency stop across all configured execution accounts. It blocks new
            live order routing, then attempts to cancel orders and flatten positions; broker actions
            may complete only partially. Also available via the Telegram /kill command.
          </p>

          {(killSwitchState === "loading" || killSwitchState === "unknown") && (
            <p className="mb-3 text-xs text-warning" role={killSwitchState === "unknown" ? "alert" : "status"}>
              {killSwitchState === "loading"
                ? "Checking authoritative kill-switch state..."
                : "Authoritative kill-switch state is unavailable. Emergency actions are disabled."}
            </p>
          )}

          {configError && safetyConfig !== undefined && (
            <p className="mb-3 text-xs text-warning" role="alert">
              The latest safety refresh failed. Showing the last known kill-switch state;
              emergency controls remain disabled until the backend responds.
            </p>
          )}

          {!isLive && (
            <p className="mb-3 text-xs text-text-muted">
              Emergency broker controls are available only in Live mode.
            </p>
          )}

          {killSwitchActive ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2 p-3 rounded-lg bg-loss/10 border border-loss/20">
                <AlertTriangle size={14} className="text-loss flex-none" />
                <p className="text-xs text-loss">
                  {flattenComplete
                    ? "Kill switch is active. New live order routing is halted and the last emergency dispatch completed."
                    : "Kill switch is active, but broker flattening is incomplete."}
                </p>
              </div>
              {!flattenComplete && safetyConfig?.emergency_result?.summary && (
                <p className="text-xs text-text-secondary" aria-live="polite">
                  {safetyConfig.emergency_result.summary}
                </p>
              )}
              {flattenComplete ? (
                <Button
                  onClick={() => resetKillMutation.mutate()}
                  disabled={resetKillMutation.isPending || !isLive || loadingConfig || configError}
                  className="bg-profit/20 hover:bg-profit/30 text-profit border border-profit/30 h-9 px-5 text-sm gap-2"
                  variant="outline"
                >
                  {resetKillMutation.isPending
                    ? <Loader2 size={14} className="animate-spin" />
                    : <ShieldCheck size={14} />
                  }
                  Reset Kill Switch — Resume Live Routing
                </Button>
              ) : (
                <Button
                  onClick={() => activateKillMutation.mutate(safetyConfig?.kill_switch_reason || killReason)}
                  disabled={
                    activateKillMutation.isPending
                    || !isLive
                    || safetyConfig === undefined
                    || loadingConfig
                    || configError
                  }
                  className="bg-loss/10 hover:bg-loss/20 text-loss border border-loss/30 h-9 px-5 text-sm gap-2"
                  variant="outline"
                >
                  {activateKillMutation.isPending
                    ? <Loader2 size={14} className="animate-spin" />
                    : <ShieldAlert size={14} />
                  }
                  Retry Emergency Actions
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <Input
                  value={killReason}
                  onChange={(e) => setKillReason(e.target.value)}
                  disabled={!isLive}
                  placeholder="Reason (optional, logged for audit)"
                  className="min-w-0 flex-[1_1_14rem] h-9 text-xs bg-surface-base border-border-default text-text-primary"
                />
                <Button
                  onClick={() => activateKillMutation.mutate(killReason)}
                  disabled={
                    activateKillMutation.isPending
                    || !isLive
                    || safetyConfig === undefined
                    || loadingConfig
                    || configError
                  }
                  variant="outline"
                  className="bg-loss/10 hover:bg-loss/20 text-loss border border-loss/30 h-9 px-5 text-sm gap-2 shrink-0"
                >
                  {activateKillMutation.isPending
                    ? <Loader2 size={14} className="animate-spin" />
                    : <ShieldAlert size={14} />
                  }
                  Activate Kill Switch
                </Button>
              </div>
            </div>
          )}
        </GlassCard>

        {/* Safety Config */}
        <GlassCard className="p-6">
          <h3 className="font-heading font-semibold text-lg text-text-primary mb-1">Safety Configuration</h3>
          <p className="text-sm text-text-secondary mb-4 leading-relaxed">
            Backend order-admission thresholds used by the safety service. Broker controls remain
            separate, and each check depends on authoritative account data being available.
          </p>

          {loadingConfig && (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={18} className="animate-spin text-text-muted" />
            </div>
          )}

          {configError && (
            <p className="text-xs text-loss text-center py-4">
              Failed to load safety config. Backend may be offline.
            </p>
          )}

          {!loadingConfig && !configError && safetyConfig && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {numericField("Max Positions",         "max_positions")}
                {numericField("Max Margin",            "max_margin_pct",       "%")}
                {numericField("Max Net Delta",         "max_net_delta")}
                {numericField("Max Net Vega",          "max_net_vega")}
              </div>

              {configDirty && (
                <div className="flex justify-end pt-2">
                  <Button
                    size="sm"
                    onClick={() => updateConfigMutation.mutate(localConfig)}
                    disabled={!isLive || updateConfigMutation.isPending}
                    className="h-8 px-5 text-xs gap-1.5"
                  >
                    {updateConfigMutation.isPending
                      ? <Loader2 size={12} className="animate-spin" />
                      : <CheckCircle2 size={12} />
                    }
                    Save Config
                  </Button>
                </div>
              )}
            </div>
          )}
        </GlassCard>

      </StaggeredList>
    </div>
  );
}
