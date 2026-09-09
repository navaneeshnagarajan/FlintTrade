export type DocsPageDescription = {
  description?: string;
  hideDescription?: boolean;
};

/**
 * Render `DocsDescription` only when the generator opts in.
 *
 * Generated docs lift the opening body paragraph into frontmatter for SEO.
 * Fail closed if `hideDescription` is missing so a stripped field cannot
 * duplicate that paragraph on `/docs*`.
 */
export function shouldRenderDocsDescription(page: DocsPageDescription): boolean {
  if (page.hideDescription !== false) return false;
  return Boolean(page.description?.trim());
}
