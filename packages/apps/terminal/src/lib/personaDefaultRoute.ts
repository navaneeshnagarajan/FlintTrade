/**
 * personaDefaultRoute — single source of truth for default workspace after auth/setup/cold return.
 * trader → Trade (execution desk)
 * beginner / investor / unknown → Home (orientation / summary surface)
 * Secondary routes (Learn, Invest, etc.) remain reachable via sidebar.
 */
export type Persona = "trader" | "investor" | "beginner";

/** Primary workspace after auth/setup/cold return. Secondary routes stay reachable. */
export function personaDefaultRoute(
  persona: Persona | string | null | undefined
): "/home" | "/trade" {
  if (persona === "trader") return "/trade";
  // beginner + investor + unknown/legacy → Home orientation first
  return "/home";
}

/**
 * Cold start path resolver (extracted for testability).
 * No settings persona → /welcome
 * Has persona → personaDefaultRoute
 */
export function getColdStartPath(
  persona: string | null | undefined,
  hasSettingsPersona: boolean
): string {
  if (!hasSettingsPersona) return "/welcome";
  return personaDefaultRoute(persona);
}
