# Domain docs

The selected layout is single-context: one `GLOSSARY.md` at the repository root and system-wide ADRs under `docs/adr/`.

## Before exploring

- Read root `GLOSSARY.md` when it exists. If root `GLOSSARY-MAP.md` exists, follow its pointers and read the glossaries relevant to the topic.
- Read ADRs under `docs/adr/` that touch the area being explored. If the repository later adopts multiple contexts, also read context-specific ADRs in the locations named by its map.
- Follow the existing architectural and contributor guidance in `docs/ARCHITECTURE.md`, `docs/DEVELOPER_GUIDE.md` and, for order-related work, `docs/ORDER_SAFETY.md`.

If a glossary, map or ADR directory is absent, proceed silently. Do not flag its absence or suggest creating empty documents. `/domain-modeling` creates them lazily when a term or decision is resolved.

## File structure

- `GLOSSARY.md`: shared domain vocabulary.
- `docs/adr/NNNN-<decision>.md`: numbered architectural decision records.

Package boundaries do not automatically define separate domain contexts. The terminal's `src/lib/glossary.ts` supports its learning UI; it is not the engineering domain glossary.

## Use the glossary's vocabulary

Use defined terms in issue titles, specs, refactor proposals, hypotheses and test names. Avoid synonyms the glossary excludes. When a concept is missing, reconsider invented language or note a real terminology gap for `/domain-modeling`.

## Flag ADR conflicts

If a proposal contradicts an existing ADR, identify the ADR and explain why the decision may need reopening. Do not silently override it.

## Preserve the design workflow

Domain docs complement the existing design record. Follow the spec-first workflow in `AGENTS.md` for working designs, design logs and the detailed working plan; `PLAN.md` is the curated public roadmap, and `changelog.md` records shipped code only.
