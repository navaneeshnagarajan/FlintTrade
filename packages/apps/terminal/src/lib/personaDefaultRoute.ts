/**
 * personaDefaultRoute — single source of truth for default workspace after auth/setup/cold return.
 * trader → Trade (execution desk)
 * beginner / investor / unknown → Home (orientation / summary surface)
 * Secondary routes (Learn, Invest, etc.) remain reachable via sidebar.
 */
export type Persona = "trader" | "investor" | "beginner";

export function personaDefaultRoute(
  persona: Persona | string | null | undefined
): "/home" | "/trade" {
  if (persona === "trader") return "/trade";
  // beginner + investor + unknown/legacy → Home orientation first
  return "/home";
}
