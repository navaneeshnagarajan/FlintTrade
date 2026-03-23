/**
 * TelegramSection — Telegram bot token, chat ID, and enable/disable toggle.
 */

import { FieldRow, TextInput, Toggle, SectionTitle } from "./shared";

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
        hint="Create a bot via @BotFather on Telegram. Stored in localStorage."
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
