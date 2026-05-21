/**
 * TelegramSection — Telegram bot token, chat ID, enable/disable toggle, and test send.
 *
 * The "Test Send" button calls the OpenAlgo POST /api/v1/telegram endpoint
 * to verify the bot token and chat ID are working.
 */

import { useState, useCallback } from "react";
import { useMutation } from "@tanstack/react-query";
import { Send, RefreshCw, CheckCircle2, AlertTriangle } from "lucide-react";
import { FieldRow, TextInput, Toggle, SectionTitle } from "./shared";
import { Button } from "@/components/ui/button";
import { sendTelegram } from "@/services/api";

interface TelegramSettings {
  enabled: boolean;
  botToken: string;
  chatId: string;
}

interface TelegramSectionProps {
  settings: TelegramSettings;
  onChangeField: (field: keyof TelegramSettings, value: string | boolean) => void;
}

export function TelegramSection({ settings, onChangeField }: TelegramSectionProps) {
  const [testStatus, setTestStatus] = useState<"idle" | "success" | "error">("idle");
  const [testError, setTestError]   = useState("");

  const testMutation = useMutation({
    mutationFn: () =>
      sendTelegram("FlintTrade test message — your Telegram integration is working!"),
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

  return (
    <div className="space-y-5">
      <SectionTitle>Telegram</SectionTitle>

      <FieldRow label="Enable Telegram notifications">
        <Toggle
          checked={settings.enabled}
          onChange={(v) => onChangeField("enabled", v)}
          label={settings.enabled ? "Enabled" : "Disabled"}
        />
      </FieldRow>

      <FieldRow
        label="Bot Token"
        hint="Create a bot via @BotFather on Telegram. Kept in memory and not persisted."
      >
        <TextInput
          value={settings.botToken}
          onChange={(v) => onChangeField("botToken", v)}
          type="password"
          placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
          disabled={!settings.enabled}
          aria-label="Telegram bot token"
        />
      </FieldRow>

      <FieldRow
        label="Chat ID"
        hint="Your personal or group chat ID. Use @userinfobot to find it."
      >
        <TextInput
          value={settings.chatId}
          onChange={(v) => onChangeField("chatId", v)}
          placeholder="-100123456789"
          disabled={!settings.enabled}
          aria-label="Telegram chat ID"
        />
      </FieldRow>

      {/* Test Send button */}
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
          <p className="font-medium text-text-primary">Telegram alerts include:</p>
          <ul className="list-disc list-inside space-y-0.5 text-text-muted">
            <li>Order placed / modified / cancelled</li>
            <li>MTM stoploss triggered</li>
            <li>MTM target reached</li>
            <li>Position closed</li>
            <li>Kill switch (send /killswitch to the bot)</li>
          </ul>
        </div>
      )}
    </div>
  );
}
