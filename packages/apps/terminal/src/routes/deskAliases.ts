/**
 * Bookmarks and older nav targets that no longer have their own page.
 *
 * Each alias lands on the screen that owns that content today.
 */
export interface DeskRouteAlias {
  path: string;
  to: string;
}

/** Public bookmarks that should open the sign-in screen, not a 404. */
export const PUBLIC_ENTRY_REDIRECTS: readonly DeskRouteAlias[] = [
  { path: "login", to: "/welcome" },
];

export const DESK_ROUTE_ALIASES: readonly DeskRouteAlias[] = [
  { path: "positions", to: "/trade#positions" },
  { path: "holdings", to: "/invest#holdings" },
  { path: "monitoring", to: "/settings#monitoring" },
  { path: "schedules", to: "/automate#schedules" },
  { path: "glossary", to: "/learn#glossary" },
];

export function deskAliasTarget(pathname: string): string | null {
  const key = pathname.replace(/^\/+/, "").replace(/\/+$/, "");
  return DESK_ROUTE_ALIASES.find((alias) => alias.path === key)?.to ?? null;
}
