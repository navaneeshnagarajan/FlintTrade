/**
 * WhatsAppSection — WhatsApp alert webhook + enable/disable toggle,
 * persisted server-side, plus a test send and the OpenAlgo pairing helpers.
 *
 * The enable flag and webhook URL persist through POST /v1/config/whatsapp:
 * the URL is stored in the backend's hardened workspace secrets (webhook
 * URLs routinely embed tokens — it never enters the browser store), and a
 * saved config takes effect on the next send. A blank URL field on save
 * preserves the stored one; reads report only whether one is set.
 *
 * The operator phone and admin URL remain local display helpers for
 * OpenAlgo's WhatsApp pairing page. Inbound slash-command support stays
 * intentionally out of scope (would bypass the mode guard).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send, RefreshCw, CheckCircle2, AlertTriangle, ExternalLink, Save } from "lucide-react";
import { FieldRow, TextInput, Toggle, SectionTitle } from "./shared";
import { Button } from "@/components/ui/button";
import { testWhatsAppAlert } from "@/services/ftApi.automation";
import { persistWhatsAppConfig, readWhatsAppConfig } from "@/services/ftApi.whatsapp";
import type { WhatsAppSettings } from "@/stores/settingsStore";

interface WhatsAppSectionProps {
  settings: WhatsAppSettings;
  onChangeField: (
    field: keyof WhatsAppSettings,
    value: string | boolean,
  ) => void;
}

export function WhatsAppSection({
  settings,
  onChangeField,
}: WhatsAppSectionProps) {
  const [testStatus, setTestStatus] = useState<"idle" | "success" | "error">("idle");
  const [testError, setTestError] = useState("");
  const [saveStatus, setSaveStatus] = useState<"idle" | "success" | "error">("idle");
  const [saveError, setSaveError] = useState("");
  // The draft URL lives only in component state — never the persisted store.
  const [webhookUrl, setWebhookUrl] = useState("");
  const queryClient = useQueryClient();

  // Hydration must never clobber an in-flight user edit (touched guard).
  const enabledTouchedRef = useRef(false);
  const changeEnabled = useCallback(
    (value: boolean) => {
      enabledTouchedRef.current = true;
      onChangeField("enabled", value);
    },
    [onChangeField],
  );

  const configQuery = useQuery({
    queryKey: ["whatsappConfig"],
    queryFn: readWhatsAppConfig,
    staleTime: 30_000,
  });
  const hydratedRef = useRef(false);
  useEffect(() => {
    const data = configQuery.data?.data;
    if (!data || hydratedRef.current) return;
    hydratedRef.current = true;
    if (!enabledTouchedRef.current) onChangeField("enabled", data.enabled);
  }, [configQuery.data, onChangeField]);

  const urlStored = configQuery.data?.data?.webhook_url_set === true;

  const saveMutation = useMutation({
    mutationFn: () =>
      persistWhatsAppConfig({ enabled: settings.enabled, webhookUrl }),
    onSuccess: () => {
      setSaveStatus("success");
      setSaveError("");
      setWebhookUrl("");
      void queryClient.invalidateQueries({ queryKey: ["whatsappConfig"] });
      setTimeout(() => setSaveStatus("idle"), 5000);
    },
    onError: (err) => {
      setSaveStatus("error");
      setSaveError(err instanceof Error ? err.message : "Save failed");
      setTimeout(() => setSaveStatus("idle"), 8000);
    },
  });

  const forgetMutation = useMutation({
    mutationFn: () =>
      // A config without a URL cannot stay enabled (fail closed), so
      // forgetting the stored URL also disables alerts.
      persistWhatsAppConfig({ enabled: false, clearWebhookUrl: true }),
    onSuccess: () => {
      onChangeField("enabled", false);
      setWebhookUrl("");
      void queryClient.invalidateQueries({ queryKey: ["whatsappConfig"] });
    },
    onError: (err) => {
      setSaveStatus("error");
      setSaveError(err instanceof Error ? err.message : "Could not forget the URL");
      setTimeout(() => setSaveStatus("idle"), 8000);
    },
  });

  const testMutation = useMutation({
    mutationFn: () =>
      testWhatsAppAlert(
        "FlintTrade test message — your WhatsApp integration is working!",
      ),
    onSuccess: () => {
      setTestStatus("success");
      setTestError("");
      setTimeout(() => setTestStatus("idle"), 5000);
    },
    onError: (err) => {
      setTestStatus("error");
      setTestError(err instanceof Error ? err.message : "Send failed");
      setTimeout(() => setTestStatus("idle"), 5000);
    },
  });

  const handleTestSend = useCallback(() => {
    testMutation.mutate();
  }, [testMutation]);

  const canSave =
    !saveMutation.isPending
    && (!settings.enabled || webhookUrl.trim().length > 0 || urlStored);

  const adminHref = settings.adminUrl?.trim() || "/whatsapp";

  return (
    <div className="space-y-5">
      <SectionTitle>WhatsApp</SectionTitle>

      <FieldRow label="Enable WhatsApp notifications">
        <Toggle
          checked={settings.enabled}
          onChange={changeEnabled}
          label={settings.enabled ? "Enabled" : "Disabled"}
        />
      </FieldRow>

      <FieldRow
        label="Webhook URL"
        hint={
          urlStored
            ? "A webhook URL is saved in the workspace secret store — leave blank to keep it, or paste a new one to replace it."
            : "Any HTTP bridge accepting a JSON POST ({\"message\": …}). Saved to the backend's hardened secret store, never the browser."
        }
      >
        <TextInput
          value={webhookUrl}
          onChange={setWebhookUrl}
          type="password"
          placeholder={urlStored ? "•••••••• (saved)" : "https://your-bridge.example/send"}
          disabled={!settings.enabled}
          aria-label="WhatsApp webhook URL"
        />
      </FieldRow>

      <FieldRow
        label="Operator phone (E.164)"
        hint="The phone number paired with OpenAlgo's WhatsApp bot. Pairing happens once via the OpenAlgo admin page below."
      >
        <TextInput
          value={settings.phoneE164}
          onChange={(v) => onChangeField("phoneE164", v)}
          placeholder="+919876543210"
          disabled={!settings.enabled}
          aria-label="WhatsApp operator phone number in E.164 format"
        />
      </FieldRow>

      <FieldRow
        label="OpenAlgo admin URL"
        hint="Override the URL of OpenAlgo's WhatsApp admin page. Leave blank to use the connected OpenAlgo host."
      >
        <TextInput
          value={settings.adminUrl}
          onChange={(v) => onChangeField("adminUrl", v)}
          placeholder="https://openalgo.local/whatsapp"
          disabled={!settings.enabled}
          aria-label="OpenAlgo WhatsApp admin URL"
        />
      </FieldRow>

      <div className="flex items-center gap-3 flex-wrap">
        <Button
          variant="default"
          size="sm"
          onClick={() => saveMutation.mutate()}
          disabled={!canSave}
          className="flex items-center gap-1.5 text-xs h-7"
        >
          {saveMutation.isPending ? (
            <RefreshCw size={11} className="animate-spin" />
          ) : (
            <Save size={11} />
          )}
          {saveMutation.isPending ? "Saving..." : "Save"}
        </Button>

        {settings.enabled && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleTestSend}
            disabled={testMutation.isPending || !settings.enabled}
            className="flex items-center gap-1.5 text-xs h-7"
          >
            {testMutation.isPending ? (
              <RefreshCw size={11} className="animate-spin" />
            ) : (
              <Send size={11} />
            )}
            {testMutation.isPending ? "Sending..." : "Test Send"}
          </Button>
        )}

        {settings.enabled && (
          <Button
            variant="outline"
            size="sm"
            asChild
            className="flex items-center gap-1.5 text-xs h-7"
          >
            <a href={adminHref} target="_blank" rel="noopener noreferrer">
              <ExternalLink size={11} />
              Pair on OpenAlgo
            </a>
          </Button>
        )}

        {urlStored && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => forgetMutation.mutate()}
            disabled={forgetMutation.isPending}
            className="flex items-center gap-1.5 text-xs h-7 text-text-muted hover:text-loss"
          >
            {forgetMutation.isPending ? "Forgetting..." : "Forget stored URL"}
          </Button>
        )}

        {saveStatus === "success" && (
          <span className="flex items-center gap-1 text-xs text-profit" role="status">
            <CheckCircle2 size={11} />
            Saved
          </span>
        )}
        {saveStatus === "error" && (
          <span className="flex items-center gap-1 text-xs text-warning" role="status">
            <AlertTriangle size={11} />
            {saveError || "Failed to save"}
          </span>
        )}
        {testStatus === "success" && (
          <span className="flex items-center gap-1 text-xs text-profit">
            <CheckCircle2 size={11} />
            Message sent
          </span>
        )}
        {testStatus === "error" && (
          <span className="flex items-center gap-1 text-xs text-warning">
            <AlertTriangle size={11} />
            {testError || "Failed to send"}
          </span>
        )}
      </div>
    </div>
  );
}
