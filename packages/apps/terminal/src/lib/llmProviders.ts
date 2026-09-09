/** Shared UI projections of generated, canonical LLM provider profiles. */

import { LLM_PROVIDER_PROFILES } from "@/generated/serviceProviders";
import type { LlmProviderId } from "@/generated/serviceProviders";

export type { LlmProviderId } from "@/generated/serviceProviders";

export interface LLMProviderConfig {
  id: LlmProviderId | typeof CLAUDE_CODE_OAUTH_PROVIDER;
  name: string;
  requiresApiKey: boolean;
  requiresHost: boolean;
  defaultHost?: string;
  defaultModel: string;
}

export type LlmAuthMode = "api-key" | "claude-code-oauth";

export const CLAUDE_CODE_OAUTH_PROVIDER = "claude-code-oauth";

function requiresApiKey(profile: (typeof LLM_PROVIDER_PROFILES)[number]): boolean {
  return (profile.authModes as readonly string[]).includes("api_key");
}

export const LLM_PROVIDERS: readonly LLMProviderConfig[] = [
  ...LLM_PROVIDER_PROFILES.map((profile) => ({
    id: profile.providerId,
    name: profile.displayName,
    requiresApiKey: requiresApiKey(profile),
    requiresHost: profile.requiresHost,
    defaultHost: profile.defaultHost || undefined,
    defaultModel: profile.defaultModel,
  })),
  {
    id: CLAUDE_CODE_OAUTH_PROVIDER,
    name: "Claude Code (OAuth)",
    requiresApiKey: true,
    requiresHost: false,
    defaultModel: LLM_PROVIDER_PROFILES.find((profile) => profile.providerId === "anthropic")?.defaultModel ?? "",
  },
];

export const LOCAL_PROVIDERS = new Set<string>(
  LLM_PROVIDER_PROFILES
    .filter((profile) => profile.managedRuntime || (profile.requiresHost && !requiresApiKey(profile)))
    .map((profile) => profile.providerId),
);

export function normaliseLlmHost(provider: string, host: string | null | undefined): string {
  return provider.trim().toLowerCase() === "ollama" ? "" : String(host ?? "");
}

export function providerSelection(selection: string): { provider: string; authMode: LlmAuthMode } {
  const normalised = selection.trim().toLowerCase();
  if (normalised === CLAUDE_CODE_OAUTH_PROVIDER) {
    return { provider: "anthropic", authMode: "claude-code-oauth" };
  }
  return { provider: normalised, authMode: "api-key" };
}

export function selectionForLlmSettings(provider: string, authMode?: LlmAuthMode): string {
  const normalised = provider.trim().toLowerCase();
  return normalised === "anthropic" && authMode === "claude-code-oauth"
    ? CLAUDE_CODE_OAUTH_PROVIDER
    : normalised;
}
