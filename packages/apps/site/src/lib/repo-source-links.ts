/**
 * Map a leftover `/docs/<repo-path>` slug to the GitHub browse URL recorded
 * while generating docs. Returns null when the slug is not a known source path.
 */
export function githubUrlForDocsSlug(
  slug: string[] | undefined,
  links: Record<string, string>,
): string | null {
  if (!slug?.length) return null;
  const key = slug.join('/').replace(/\/+$/, '');
  return links[key] ?? null;
}
