/**
 * LLMSection — LLM provider, model, host URL, and API key configuration.
 */

import { FieldRow, SelectInput, TextInput, SectionTitle } from "./shared";

type LlmProvider =
  | "lmstudio"
  | "ollama"
  | "openai"
  | "anthropic"
  | "gemini"
  | "deepseek"
  | "groq"
  | "grok"
  | "mistral"
  | "together"
  | "openrouter"
  | "custom";

interface LlmSettings {
  provider: LlmProvider;
  host: string;
  model: string;
  apiKey: string;
}

const LOCAL_PROVIDERS = new Set<LlmProvider>(["lmstudio", "ollama", "custom"]);

const LLM_PROVIDER_OPTIONS = [
  { value: "lmstudio",   label: "LM Studio (local)"  },
  { value: "ollama",     label: "Ollama (local)"      },
  { value: "openai",     label: "OpenAI"              },
  { value: "anthropic",  label: "Anthropic"           },
  { value: "gemini",     label: "Google Gemini"       },
  { value: "deepseek",   label: "DeepSeek"            },
  { value: "groq",       label: "Groq"                },
  { value: "grok",       label: "Grok (xAI)"         },
  { value: "mistral",    label: "Mistral"             },
  { value: "together",   label: "Together AI"         },
  { value: "openrouter", label: "OpenRouter"          },
  { value: "custom",     label: "Custom endpoint"     },
];

interface LLMSectionProps {
  settings: LlmSettings;
  onChange: (field: keyof LlmSettings, value: string) => void;
}

export function LLMSection({ settings, onChange }: LLMSectionProps) {
  const isLocal = LOCAL_PROVIDERS.has(settings.provider);

  return (
    <div className="space-y-5">
      <SectionTitle>LLM Config</SectionTitle>

      <FieldRow
        label="Provider"
        hint="Local providers (LM Studio, Ollama) run on your machine — no API key needed."
      >
        <SelectInput
          value={settings.provider}
          onChange={(v) => onChange("provider", v)}
          options={LLM_PROVIDER_OPTIONS}
          aria-label="LLM provider"
        />
      </FieldRow>

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
          hint="Provider API key. Stored in localStorage — do not use on shared machines."
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
    </div>
  );
}
