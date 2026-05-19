# FlintTrade — chrome-extension

> Quick-order companion extension. Read `packages/chrome-extension/CLAUDE.md` first.

## Absorbs
- openalgo-chrome → popup layout patterns, content-script symbol detection

## Depends on: terminal (shares backend `/ft-api/v1/*` contract)

## Rules
- Read root CLAUDE.md for project-wide rules.
- Manifest V3 only — no persistent background pages.
- Never reference specific brokers; speak only via FlintTrade backend abstraction.
- API key lives in `chrome.storage.local`, never in source or `chrome.storage.sync`.
- Tests (if added) belong alongside the modified file as `*.test.js`.
- Update root CHANGELOG.md for user-visible changes.
- Branch: main (pre-release, all commits to main).
