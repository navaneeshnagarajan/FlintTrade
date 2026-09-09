/**
 * Docs page summaries are lifted from the first body paragraph for SEO.
 * The on-page DocsDescription must not repeat that same opening paragraph.
 */

export function stripInlineMarkdown(value) {
  return value
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[*_~]/g, '');
}

export function firstBodyParagraph(markdown) {
  const withoutTitle = String(markdown ?? '')
    .replace(/^#\s+.+$/m, '')
    .trim();

  return withoutTitle
    .split(/\n\s*\n/)
    .map((part) => part.trim())
    .find((part) => part && !part.startsWith('```') && !part.startsWith('|') && !part.startsWith('<'));
}

export function descriptionFromMarkdown(markdown, fallback) {
  const paragraph = firstBodyParagraph(markdown);
  if (!paragraph) return fallback;

  return stripInlineMarkdown(paragraph)
    .replace(/^>\s*/, '')
    .replace(/\s+/g, ' ')
    .slice(0, 180)
    .trim();
}

export function normaliseDescriptionText(value) {
  return stripInlineMarkdown(String(value ?? ''))
    .replace(/^>\s*/, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

export function descriptionDuplicatesOpeningBody(description, bodyMarkdown) {
  const desc = normaliseDescriptionText(description);
  const opening = firstBodyParagraph(bodyMarkdown);
  if (!desc || !opening) return false;

  const lead = normaliseDescriptionText(opening);
  if (!lead) return false;

  return lead === desc || lead.startsWith(desc) || desc.startsWith(lead);
}

export function shouldHidePageDescription(description, bodyMarkdown) {
  return descriptionDuplicatesOpeningBody(description, bodyMarkdown);
}

export function shouldRenderDocsDescription(page) {
  if (page?.hideDescription !== false) return false;
  return Boolean(String(page?.description ?? '').trim());
}
