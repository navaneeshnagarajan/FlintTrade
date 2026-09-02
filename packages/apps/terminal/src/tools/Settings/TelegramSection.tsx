/**
 * TelegramSection — Telegram bot token, chat ID, enable/disable toggle,
 * persisted server-side plus a test send.
 *
 * Settings persist through POST /v1/config/telegram: the token is stored in
 * the backend's hardened workspace secrets (never in the browser or
 * workspace.json), and a saved config is applied to the running kill-switch
 * bot without a backend restart. A blank token field on save preserves the
 * stored token; reads report only whether one is set.
 */

import { useState, useCallback, useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send, RefreshCw, CheckCircle2, AlertTriangle, Save } from "lucide-react";
import { FieldRow, TextInput, Toggle, SectionTitle } from "./shared";
import { Button } from "@/components/ui/button";
import { sendTelegram } from "@/services/api";
import { persistTelegramConfig, readTelegramConfig } from "@/services/ftApi.telegram";

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
  const [saveStatus, setSaveStatus] = useState<"idle" | "success" | "error">("idle");
  const [saveError, setSaveError]   = useState("");
  const [saveMessage, setSaveMessage] = useState("");
  const queryClient = useQueryClient();

  // Track which fields the user has edited: hydration must never clobber an
  // in-flight edit made before the (possibly slow) config query resolves.
  const touchedRef = useRef<Set<keyof TelegramSettings>>(new Set());
  const changeField = useCallback(
    (field: keyof TelegramSettings, value: string | boolean) => {
      touchedRef.current.add(field);
      onChangeField(field, value);
    },
    [onChangeField],
  );

  // Hydrate the untouched fields once from the backend's redacted state so a
  // reload shows the real saved settings instead of blank fields.
  const configQuery = useQuery({
    queryKey: ["telegramConfig"],
    queryFn: readTelegramConfig,
    staleTime: 30_000,
  });
  const hydratedRef = useRef(false);
  useEffect(() => {
    const data = configQuery.data?.data;
    if (!data || hydratedRef.current) return;
    hydratedRef.current = true;
    if (!touchedRef.current.has("enabled")) onChangeField("enabled", data.enabled);
    if (!touchedRef.current.has("chatId")) onChangeField("chatId", data.chat_id);
  }, [configQuery.data, onChangeField]);

  const tokenStored = configQuery.data?.data?.bot_token_set === true;

  const saveMutation = useMutation({
    mutationFn: (payload: TelegramSettings) => persistTelegramConfig(payload),
    onSuccess: (response) => {
      setSaveStatus("success");
      setSaveError("");
      // Report what the backend actually did (it says whether the running
      // bot is being updated) instead of hardcoding an applied claim.
      setSaveMessage(response.message || "Saved");
      // The token now lives server-side; drop it from browser memory.
      onChangeField("botToken", "");
      void queryClient.invalidateQueries({ queryKey: ["telegramConfig"] });
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
      persistTelegramConfig({
        // A config without a token cannot stay enabled (fail closed), so
        // forgetting the stored token also disables the bot.
        enabled: false,
        chatId: settings.chatId,
        clearToken: true,
      }),
    onSuccess: () => {
      onChangeField("enabled", false);
      onChangeField("botToken", "");
      void queryClient.invalidateQueries({ queryKey: ["telegramConfig"] });
    },
    onError: (err) => {
      setSaveStatus("error");
      setSaveError(err instanceof Error ? err.message : "Could not forget the token");
      setTimeout(() => setSaveStatus("idle"), 8000);
    },
  });

  const testMutation = useMutation({
    mutationFn: () =>
      sendTelegram("FlintTrade test message — your Telegram integration is working!", {
        botToken: settings.botToken,
        chatId: settings.chatId,
      }),
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
    && (!settings.enabled
      || (settings.chatId.trim().length > 0
        && (settings.botToken.trim().length > 0 || tokenStored)));

  return (
    <div className="space-y-5">
      <SectionTitle>Telegram</SectionTitle>

      <FieldRow label="Enable Telegram notifications">
        <Toggle
          checked={settings.enabled}
          onChange={(v) => changeField("enabled", v)}
          label={settings.enabled ? "Enabled" : "Disabled"}
        />
      </FieldRow>

      <FieldRow
        label="Bot Token"
        hint={
          tokenStored
            ? "A token is saved in the workspace secret store — leave blank to keep it, or paste a new one to replace it."
            : "Create a bot via @BotFather on Telegram. Saved to the backend's hardened secret store, never the browser."
        }
      >
        <TextInput
          value={settings.botToken}
          onChange={(v) => changeField("botToken", v)}
          type="password"
          placeholder={tokenStored ? "•••••••• (saved)" : "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"}
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
          onChange={(v) => changeField("chatId", v)}
          placeholder="-100123456789"
          disabled={!settings.enabled}
          aria-label="Telegram chat ID"
        />
      </FieldRow>

      {/* Save + Test */}
      <div className="flex items-center gap-3">
        <Button
          variant="default"
          size="sm"
          onClick={() =>
            saveMutation.mutate({
              enabled: settings.enabled,
              chatId: settings.chatId,
              botToken: settings.botToken,
            })
          }
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
            disabled={
              testMutation.isPending
              || !settings.enabled
              // The backend send route falls back to the STORED config when
              // credentials are omitted, so a freshly-saved token (cleared
              // from browser memory) still supports Test Send.
              || !(settings.botToken.trim() || tokenStored)
              || !settings.chatId.trim()
            }
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

        {tokenStored && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => forgetMutation.mutate()}
            disabled={forgetMutation.isPending}
            className="flex items-center gap-1.5 text-xs h-7 text-text-muted hover:text-loss"
          >
            {forgetMutation.isPending ? "Forgetting..." : "Forget stored token"}
          </Button>
        )}

        {saveStatus === "success" && (
          <span className="flex items-center gap-1 text-xs text-profit" role="status">
            <CheckCircle2 size={11} />
            {saveMessage || "Saved"}
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
