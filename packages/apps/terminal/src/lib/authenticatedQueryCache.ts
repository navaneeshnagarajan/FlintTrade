let purgeRegisteredCache: (() => void) | null = null;

/** Register the application-owned authenticated query cache boundary. */
export function registerAuthenticatedQueryCachePurge(purge: () => void): void {
  purgeRegisteredCache = purge;
}

/** Purge principal-scoped server state without coupling auth state to React Query. */
export function purgeAuthenticatedQueryCache(): void {
  purgeRegisteredCache?.();
}
