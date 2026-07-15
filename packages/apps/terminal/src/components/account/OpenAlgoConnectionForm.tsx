/**
 * Shared OpenAlgo connection editor for Setup and Settings.
 *
 * Candidate values remain local to the form. The runtime connection cache is
 * updated only after the backend accepts one complete configuration save.
 */

import { useEffect, useMemo, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, CheckCircle, Loader2, Save, Wifi, XCircle } from "lucide-react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useTestConnection } from "@/hooks/useTestConnection";
import {
  editableConnectionSchema,
  deriveWsUrl,
  type ConnectionFormValues,
} from "@/routes/setup/connectionForm";
import {
  applyOpenAlgoRestPort,
  persistOpenAlgoConfigPatch,
} from "@/services/ftApi.openalgo";
import { useConnectionStore } from "@/stores/connectionStore";

interface OpenAlgoConnectionFormProps {
  defaultValues?: Partial<ConnectionFormValues>;
  apiKeyConfigured?: boolean;
  apiKeyLast4?: string;
  submitLabel?: string;
  submitIcon?: "arrow" | "save";
  onSaved?: (values: ConnectionFormValues) => void;
}

type SaveState = "idle" | "saving" | "saved" | "error";

const DEFAULT_VALUES: ConnectionFormValues = {
  host: "http://localhost:5000",
  port: "5000",
  apiKey: "",
  wsPort: "8765",
};

export function OpenAlgoConnectionForm({
  defaultValues,
  apiKeyConfigured = false,
  apiKeyLast4 = "",
  submitLabel = "Continue",
  submitIcon = "arrow",
  onSaved,
}: OpenAlgoConnectionFormProps) {
  const cachedApiKey = useConnectionStore((state) => state.apiKey);
  const hasConfiguredApiKey = apiKeyConfigured || Boolean(cachedApiKey);
  const initialValues = useMemo<ConnectionFormValues>(() => ({
    host: defaultValues?.host ?? DEFAULT_VALUES.host,
    port: defaultValues?.port ?? DEFAULT_VALUES.port,
    apiKey: defaultValues?.apiKey ?? DEFAULT_VALUES.apiKey,
    wsPort: defaultValues?.wsPort ?? DEFAULT_VALUES.wsPort,
  }), [defaultValues?.apiKey, defaultValues?.host, defaultValues?.port, defaultValues?.wsPort]);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState("");
  const {
    register,
    handleSubmit,
    getValues,
    reset: resetForm,
    setError,
    formState: { errors, isDirty },
  } = useForm<ConnectionFormValues>({
    resolver: zodResolver(editableConnectionSchema),
    defaultValues: initialValues,
  });
  const {
    status: testState,
    message: testMessage,
    testConnection,
    reset: resetTest,
  } = useTestConnection();

  // Settings may mount before the authenticated workspace read completes.
  // Apply late authoritative defaults only while the operator has not started
  // editing, so hydration can never overwrite a candidate configuration.
  useEffect(() => {
    if (!isDirty) resetForm(initialValues);
  }, [initialValues, isDirty, resetForm]);

  function handleCandidateChange() {
    if (saveState !== "saving") setSaveState("idle");
    setSaveError("");
    resetTest();
  }

  async function handleTest() {
    const values = getValues();
    const candidateApiKey = values.apiKey.trim() || cachedApiKey;
    if (!candidateApiKey) {
      setSaveError("Enter an OpenAlgo API key before testing the connection.");
      return;
    }
    setSaveError("");
    await testConnection(
      applyOpenAlgoRestPort(values.host.trim(), values.port.trim()),
      candidateApiKey,
    );
  }

  async function handleSave(values: ConnectionFormValues) {
    const replacementApiKey = values.apiKey.trim();
    if (!replacementApiKey && !hasConfiguredApiKey) {
      setError("apiKey", {
        type: "manual",
        message: "API key must be at least 8 characters",
      });
      return;
    }

    const acceptedValues: ConnectionFormValues = {
      host: values.host.trim(),
      port: values.port.trim(),
      apiKey: replacementApiKey,
      wsPort: values.wsPort.trim(),
    };
    setSaveState("saving");
    setSaveError("");
    try {
      const result = await persistOpenAlgoConfigPatch({
        host: acceptedValues.host,
        port: acceptedValues.port,
        wsPort: acceptedValues.wsPort,
        ...(replacementApiKey ? { apiKey: replacementApiKey } : {}),
      });
      if (result.status === "partial") {
        setSaveState("error");
        setSaveError(
          result.message
            || "The connection was saved, but FlintTrade could not apply it completely. Retry or restart before continuing.",
        );
        return;
      }

      const effectiveApiKey = replacementApiKey || cachedApiKey;
      const connectionStore = useConnectionStore.getState();
      connectionStore.setConfig({
        host: acceptedValues.host,
        apiKey: effectiveApiKey,
        wsUrl: deriveWsUrl(acceptedValues.host, acceptedValues.wsPort),
      });
      if (effectiveApiKey) connectionStore.setOpenAlgoHydrated(true);
      setSaveState("saved");
      resetForm({ ...acceptedValues, apiKey: "" });
      onSaved?.(acceptedValues);
    } catch (error) {
      setSaveState("error");
      setSaveError(
        error instanceof Error
          ? error.message
          : "The OpenAlgo connection could not be saved.",
      );
    }
  }

  return (
    <form
      onSubmit={handleSubmit(handleSave)}
      onChange={handleCandidateChange}
      className="space-y-5"
    >
      <div className="space-y-1.5">
        <Label htmlFor="openalgo-host" className="text-text-secondary text-xs uppercase tracking-wider">
          OpenAlgo-Compatible URL
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="openalgo-host"
            placeholder="http://localhost:5000"
            aria-label="OpenAlgo-compatible URL"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("host")}
          />
        </div>
        {errors.host && <p className="text-red-400 text-xs">{errors.host.message}</p>}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="openalgo-port" className="text-text-secondary text-xs uppercase tracking-wider">
          REST Port
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="openalgo-port"
            placeholder="5000"
            aria-label="REST port"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("port")}
          />
        </div>
        {errors.port && <p className="text-red-400 text-xs">{errors.port.message}</p>}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="openalgo-api-key" className="text-text-secondary text-xs uppercase tracking-wider">
          API Key
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="openalgo-api-key"
            type="password"
            autoComplete="new-password"
            placeholder={hasConfiguredApiKey ? "Enter a replacement key" : "Your gateway API key"}
            aria-label="OpenAlgo-compatible API key"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("apiKey")}
          />
        </div>
        {hasConfiguredApiKey && (
          <p className="text-text-muted text-xs">
            A key is saved{apiKeyLast4 ? ` ending in ${apiKeyLast4}` : ""}. Leave this blank to keep it.
          </p>
        )}
        {errors.apiKey && <p className="text-red-400 text-xs">{errors.apiKey.message}</p>}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="openalgo-ws-port" className="text-text-secondary text-xs uppercase tracking-wider">
          WebSocket Port
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="openalgo-ws-port"
            placeholder="8765"
            aria-label="WebSocket port"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("wsPort")}
          />
        </div>
        {errors.wsPort && <p className="text-red-400 text-xs">{errors.wsPort.message}</p>}
      </div>

      <div className="flex flex-wrap items-center gap-3 pt-1">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void handleTest()}
          disabled={testState === "testing" || saveState === "saving"}
          className="border-border-default text-text-secondary hover:text-text-primary"
        >
          {testState === "testing" ? (
            <Loader2 className="size-3.5 mr-1.5 animate-spin" />
          ) : (
            <Wifi className="size-3.5 mr-1.5" />
          )}
          Test Connection
        </Button>

        {testState === "ok" && (
          <span className="flex items-center gap-1.5 text-green-400 text-sm">
            <CheckCircle className="size-4" /> Connected
          </span>
        )}
        {testState === "error" && (
          <span className="flex items-center gap-1.5 text-red-400 text-sm">
            <XCircle className="size-4" />
            <span className="truncate max-w-50">{testMessage || "Failed"}</span>
          </span>
        )}
      </div>

      {saveError && (
        <p role="alert" className="text-xs text-red-400">
          {saveError}
        </p>
      )}
      {saveState === "saved" && (
        <p role="status" className="text-xs text-green-400">
          Connection settings saved.
        </p>
      )}

      <Button
        type="submit"
        disabled={saveState === "saving"}
        className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
      >
        {saveState === "saving" ? <Loader2 className="size-4 mr-2 animate-spin" /> : null}
        {saveState === "saving" ? "Saving…" : submitLabel}
        {saveState !== "saving" && submitIcon === "arrow" && <ArrowRight className="size-4 ml-2" />}
        {saveState !== "saving" && submitIcon === "save" && <Save className="size-4 ml-2" />}
      </Button>
    </form>
  );
}
