/**
 * LLMSection — LLM provider, model, host URL, and API key configuration.
 */

import { useState, useCallback } from "react";
import { CheckCircle2, AlertCircle, Loader2 } from "lucide-react";
import { FieldRow, SelectInput, TextInput, SectionTitle } from "./shared";
import { LLM_PROVIDERS, LOCAL_PROVIDERS } from "@/lib/llmProviders";

type LlmProvider =
  | "lmstudio"
  | "ollama"
  | "hermes"
  | "openai"
  | "anthropic"
  | "gemini"
  | "deepseek"
  | "groq"
  | "grok"
  | "mistral"
  | "cerebras"
  | "together"
  | "openrouter"
  | "custom";

/**
 * UI-only dropdown value for "Claude Code (OAuth)". It is not a distinct backend
 * provider — it persists as `anthropic`, and the backend chooses the OAuth
 * (Bearer) auth scheme automatically from the token's shape. A session-local
 * flag keeps the dropdown showing this label after the operator selects it.
 */
const CLAUDE_CODE_OAUTH = "claude-code-oauth";

interface LlmSettings {
  provider: LlmProvider;
  host: string;
  model: string;
  apiKey: string;
}

const LLM_PROVIDER_OPTIONS = LLM_PROVIDERS.map((p) => ({ value: p.id, label: p.name }));

interface LLMSectionProps {
  settings: LlmSettings;
  onChange: (field: keyof LlmSettings, value: string) => void;
}

type TestStatus = "idle" | "testing" | "ok" | "error";

function buildTestUrl(provider: LlmProvider, host: string): string | null {
  switch (provider) {
    case "lmstudio":
    case "ollama":
    case "hermes":
    case "custom":
      return host ? `${host.replace(/\/$/, "")}/v1/models` : null;
    case "openai":
      return "https://api.openai.com/v1/models";
    case "anthropic":
      return "https://api.anthropic.com/v1/models";
    case "gemini":
      return "https://generativelanguage.googleapis.com/v1beta/models";
    case "deepseek":
      return "https://api.deepseek.com/v1/models";
    case "groq":
      return "https://api.groq.com/openai/v1/models";
    case "mistral":
      return "https://api.mistral.ai/v1/models";
    case "cerebras":
      return "https://api.cerebras.ai/v1/models";
    case "together":
      return "https://api.together.xyz/v1/models";
    case "openrouter":
      return "https://openrouter.ai/api/v1/models";
    default:
      return null;
  }
}

export function LLMSection({ settings, onChange }: LLMSectionProps) {
  const isLocal = LOCAL_PROVIDERS.has(settings.provider);
  const [testStatus, setTestStatus] = useState<TestStatus>("idle");
  const [testMessage, setTestMessage] = useState<string>("");
  // "Claude Code (OAuth)" persists as `anthropic`; this keeps the dropdown
  // showing the OAuth label for the rest of the session after selection.
  const [oauthSelected, setOauthSelected] = useState(false);

  // The value shown in the provider dropdown: the OAuth alias when the operator
  // picked it this session and the underlying provider is still Anthropic,
  // otherwise the persisted provider itself.
  const selectedProvider =
    oauthSelected && settings.provider === "anthropic" ? CLAUDE_CODE_OAUTH : settings.provider;
  const isClaudeCodeOAuth = selectedProvider === CLAUDE_CODE_OAUTH;

  const handleProviderChange = useCallback(
    (value: string) => {
      setTestStatus("idle");
      setTestMessage("");
      if (value === CLAUDE_CODE_OAUTH) {
        // A UI alias for Anthropic + an OAuth-shaped token — persist the real
        // backend provider so the request routes through the Anthropic transport.
        setOauthSelected(true);
        onChange("provider", "anthropic");
        return;
      }
      setOauthSelected(false);
      onChange("provider", value);
    },
    [onChange],
  );

  const handleTestConnection = useCallback(async () => {
    setTestStatus("testing");
    setTestMessage("");

    const url = buildTestUrl(settings.provider, settings.host);
    if (!url) {
      setTestStatus("error");
      setTestMessage("Enter a host URL before testing.");
      return;
    }

    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (settings.apiKey) {
        headers["Authorization"] = `Bearer ${settings.apiKey}`;
      }
      const resp = await fetch(url, { method: "GET", headers, signal: AbortSignal.timeout(8000) });
      if (resp.ok) {
        setTestStatus("ok");
        setTestMessage("Connection successful.");
      } else {
        setTestStatus("error");
        setTestMessage(`Server returned ${resp.status}. Check API key or host URL.`);
      }
    } catch (e) {
      setTestStatus("error");
      setTestMessage(e instanceof Error ? e.message : "Connection failed.");
    }
  }, [settings.provider, settings.host, settings.apiKey]);

  return (
    <div className="space-y-5">
      <SectionTitle>LLM Config</SectionTitle>

      <FieldRow
        label="Provider"
        hint="Local providers (LM Studio, Ollama) run on your machine — no API key needed."
      >
        <SelectInput
          value={selectedProvider}
          onChange={handleProviderChange}
          options={LLM_PROVIDER_OPTIONS}
          aria-label="LLM provider"
        />
      </FieldRow>

      {isClaudeCodeOAuth && (
        <p className="text-xs text-text-muted -mt-2">
          Claude Code (OAuth) uses the Anthropic endpoint. Paste your Claude Code OAuth
          token (starts with <code className="font-mono">sk-ant-oat-</code>,{" "}
          <code className="font-mono">cc-</code>, or a JWT) into the API key field —
          FlintTrade detects the OAuth scheme automatically.
        </p>
      )}

      {isLocal && (
        <FieldRow
          label="Host URL"
          hint="Base URL of the local inference server."
        >
          <TextInput
            value={settings.host}
            onChange={(v) => onChange("host", v)}
            placeholder={settings.provider === "ollama" ? "http://127.0.0.1:11434" : "http://127.0.0.1:1234"}
            aria-label="LLM host URL"
          />
        </FieldRow>
      )}

      <FieldRow
        label="Model Name"
        hint={isLocal ? "Model identifier as listed in your local server (e.g. qwen3:9b)." : "Model identifier from the provider (e.g. gpt-4o)."}
      >
        <TextInput
          value={settings.model}
          onChange={(v) => onChange("model", v)}
          placeholder={isLocal ? "e.g. qwen3:9b" : "e.g. gpt-4o"}
          aria-label="LLM model name"
        />
      </FieldRow>

      {!isLocal && (
        <FieldRow
          label="API Key"
          hint="Provider API key. Stored in the local hardened workspace; re-enter to replace it."
        >
          <TextInput
            value={settings.apiKey}
            onChange={(v) => onChange("apiKey", v)}
            type="password"
            placeholder="sk-••••••••••••••••"
            aria-label="LLM provider API key"
          />
        </FieldRow>
      )}

      {settings.provider === "custom" && (
        <FieldRow
          label="Custom Endpoint Base URL"
          hint="Full base URL of an OpenAI-compatible custom endpoint."
        >
          <TextInput
            value={settings.host}
            onChange={(v) => onChange("host", v)}
            placeholder="https://your-custom-endpoint.example.com"
            aria-label="Custom LLM endpoint URL"
          />
        </FieldRow>
      )}

      {/* Test Connection */}
      <div className="flex items-center gap-3 pt-1">
        <button
          type="button"
          onClick={() => void handleTestConnection()}
          disabled={testStatus === "testing"}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded border border-border-default bg-surface-hover text-text-secondary hover:text-text-primary hover:border-accent/40 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {testStatus === "testing" ? (
            <Loader2 size={12} className="animate-spin" />
          ) : testStatus === "ok" ? (
            <CheckCircle2 size={12} className="text-profit" />
          ) : testStatus === "error" ? (
            <AlertCircle size={12} className="text-loss" />
          ) : null}
          Test Connection
        </button>
        {testMessage && (
          <span className={`text-xs ${testStatus === "ok" ? "text-profit" : "text-loss"}`}>
            {testMessage}
          </span>
        )}
      </div>
    </div>
  );
}
