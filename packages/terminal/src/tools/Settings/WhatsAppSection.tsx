/**
 * WhatsAppSection — WhatsApp alert webhook + enable/disable toggle + test send.
 *
 * The "Test Send" button calls the FlintTrade POST /api/v1/alerts/whatsapp/test
 * endpoint (proxied to OpenAlgo's WhatsApp bot, added upstream in v2.0.1.1).
 * Upstream deliberately exposes only POST /api/v1/whatsapp/notify as a public
 * API surface — pairing, start/stop, and config are admin-only on the OpenAlgo
 * web UI, so a leaked API key cannot re-pair or wipe the Signal session.
 *
 * FlintTrade keeps a thin outbound-only wrapper here; inbound slash-command
 * support is intentionally out of scope (would bypass the mode guard).
 */

import { useCallback, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Send, RefreshCw, CheckCircle2, AlertTriangle, ExternalLink } from "lucide-react";
import { FieldRow, TextInput, Toggle, SectionTitle } from "./shared";
import { Button } from "@/components/ui/button";
import { testWhatsAppAlert } from "@/services/ftApi.automation";
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

  const adminHref = settings.adminUrl?.trim() || "/whatsapp";

  return (
    <div className="space-y-5">
      <SectionTitle>WhatsApp</SectionTitle>

      <FieldRow label="Enable WhatsApp notifications">
        <Toggle
          checked={settings.enabled}
          onChange={(v) => onChangeField("enabled", v)}
          label={settings.enabled ? "Enabled" : "Disabled"}
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

      {settings.enabled && (
        <div className="flex items-center gap-3">
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
      )}

      {settings.enabled && (
        <div className="p-3 rounded bg-accent/5 border border-accent/20 text-xs text-text-secondary space-y-1">
          <p className="font-medium text-text-primary">WhatsApp alerts include:</p>
          <ul className="list-disc list-inside space-y-0.5 text-text-muted">
            <li>Order placed / modified / cancelled</li>
            <li>MTM stoploss triggered</li>
            <li>MTM target reached</li>
            <li>Position closed</li>
            <li>GTT trigger fired (Dhan, Zerodha)</li>
          </ul>
          <p className="pt-1 text-text-muted">
            FlintTrade does not consume WhatsApp slash commands — inbound
            messaging is intentionally outbound-only here so orders cannot
            bypass the explore / practice / live mode guard.
          </p>
        </div>
      )}
    </div>
  );
}
