/**
 * llmProviders — shared LLM provider configuration.
 * Used by LLMSection (Settings) and LlmStep (setup wizard).
 */

export interface LLMProviderConfig {
  id: string;
  name: string;
  requiresApiKey: boolean;
  requiresHost: boolean;
  defaultHost?: string;
}

export const LLM_PROVIDERS: readonly LLMProviderConfig[] = [
  { id: "lmstudio",   name: "LM Studio",     requiresApiKey: false, requiresHost: true,  defaultHost: "http://127.0.0.1:1234"   },
  { id: "ollama",     name: "Ollama",         requiresApiKey: false, requiresHost: true,  defaultHost: "http://127.0.0.1:11434"  },
  { id: "hermes",     name: "Hermes (Nous)",  requiresApiKey: false, requiresHost: true,  defaultHost: "http://127.0.0.1:11434"  },
  { id: "openai",     name: "OpenAI",         requiresApiKey: true,  requiresHost: false                                         },
  { id: "anthropic",  name: "Anthropic",      requiresApiKey: true,  requiresHost: false                                         },
  // "Claude Code (OAuth)" is the Anthropic provider driven with an OAuth-shaped
  // token (Claude Code credits). It persists as `anthropic`; LLMSection maps the
  // selection and the auth scheme is chosen from the token's shape by the backend.
  { id: "claude-code-oauth", name: "Claude Code (OAuth)", requiresApiKey: true, requiresHost: false                             },
  { id: "gemini",     name: "Google Gemini",  requiresApiKey: true,  requiresHost: false                                         },
  { id: "deepseek",   name: "DeepSeek",       requiresApiKey: true,  requiresHost: false                                         },
  { id: "groq",       name: "Groq",           requiresApiKey: true,  requiresHost: false                                         },
  { id: "grok",       name: "Grok (xAI)",     requiresApiKey: true,  requiresHost: false                                         },
  { id: "mistral",    name: "Mistral",        requiresApiKey: true,  requiresHost: false                                         },
  { id: "cerebras",   name: "Cerebras",       requiresApiKey: true,  requiresHost: false                                         },
  { id: "together",   name: "Together AI",    requiresApiKey: true,  requiresHost: false                                         },
  { id: "openrouter", name: "OpenRouter",     requiresApiKey: true,  requiresHost: false                                         },
  { id: "custom",     name: "Custom Endpoint",requiresApiKey: true,  requiresHost: true                                          },
] as const;

export const LOCAL_PROVIDERS = new Set(["lmstudio", "ollama", "hermes", "custom"]);
