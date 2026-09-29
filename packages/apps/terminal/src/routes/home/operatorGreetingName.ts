/**
 * Home greeting name for the signed-in operator.
 *
 * On mount, the saved display name is the greeting. The username is used
 * only when no display name is saved, so a reload does not flash the
 * username first. A profile edit after that replaces it. "Trader" is the
 * unset placeholder, not an operator name.
 */

import { useRef } from "react";
import { useAuthStore } from "@/stores/authStore";
import { useSettingsStore } from "@/stores/settingsStore";

const PLACEHOLDER_NAME = "trader";

export function realOperatorName(value: string | null | undefined): string | null {
  const trimmed = value?.trim() ?? "";
  if (!trimmed || trimmed.toLowerCase() === PLACEHOLDER_NAME) return null;
  return trimmed;
}

export interface GreetingBinding {
  generation: number;
  settingsAtEntry: string;
  name: string | null;
}

function greetingName(settingsName: string, username: string | null): string | null {
  return realOperatorName(settingsName) ?? realOperatorName(username);
}

export function nextGreetingBinding(
  previous: GreetingBinding | null,
  input: {
    generation: number;
    username: string | null;
    settingsName: string;
    loggedIn: boolean;
  },
): GreetingBinding {
  if (previous == null || previous.generation !== input.generation || !input.loggedIn) {
    return {
      generation: input.generation,
      settingsAtEntry: input.settingsName,
      name: input.loggedIn ? greetingName(input.settingsName, input.username) : null,
    };
  }
  if (input.settingsName !== previous.settingsAtEntry) {
    return {
      generation: input.generation,
      settingsAtEntry: input.settingsName,
      name: greetingName(input.settingsName, input.username),
    };
  }
  // Sign-in passes through a logged-out frame on the new generation. The
  // completed session still supplies the saved name, or the username.
  if (previous.name == null) {
    return {
      ...previous,
      name: greetingName(input.settingsName, input.username),
    };
  }
  return previous;
}

/** Display name for this auth session. Re-reads when the session changes. */
export function useOperatorGreetingName(): string | null {
  const username = useAuthStore((s) => s.username);
  const generation = useAuthStore((s) => s.sessionGeneration);
  const loggedIn = useAuthStore((s) => s.status === "logged-in");
  const settingsName = useSettingsStore((s) => s.name);
  const binding = useRef<GreetingBinding | null>(null);
  binding.current = nextGreetingBinding(binding.current, {
    generation,
    username,
    settingsName,
    loggedIn,
  });
  return binding.current.name;
}
