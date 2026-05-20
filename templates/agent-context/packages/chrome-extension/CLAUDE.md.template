# FlintTrade — chrome-extension

> Browser companion for FlintTrade — quick order entry, connection status, and symbol detection on Indian market sites

## Key Files
- `manifest.json` — Chrome Extension Manifest V3 declaration (permissions, scripts, popup)
- `popup.html` / `popup.css` / `popup.js` — Toolbar popup UI (connection status, quick order form, recent signals)
- `content.js` / `content.css` — Page content script that detects stock symbols on NSE India / Moneycontrol and adds "Trade" buttons inline
- `icons/` — Extension icon (16/32/48/128 px)

## Architecture
- Manifest V3 service worker model — no persistent background page.
- The popup talks to the FlintTrade backend over the same `/ft-api/v1/*` REST surface that the main React terminal uses.
- The content script never holds the user's API key directly; it `chrome.runtime.sendMessage`s the popup, which holds the key in `chrome.storage.local`.
- Supported sites today: NSE India quote pages, Moneycontrol stock pages.

## Depends on: terminal (shares backend contract, NOT JavaScript code)

## Local install (developer mode)
1. `chrome://extensions/` → enable Developer mode
2. Load unpacked → select `packages/chrome-extension/`
3. Pin the FlintTrade icon
4. Settings → host = `http://localhost:5173`, API key from in-app Settings → Connection

## Rules
- Read root CLAUDE.md for project-wide rules.
- Manifest V3 only. Do not introduce `chrome.tabs.executeScript` or other MV2 APIs.
- Never embed broker names in the popup UI — speak through the FlintTrade backend abstraction.
- API key MUST be stored via `chrome.storage.local`, never in code or in `chrome.storage.sync` (sync would replicate to other Chrome profiles).
- Do not import the React terminal's bundle into the popup — keep the extension lightweight and independently versioned.
- Tests for the popup live alongside source as `*.test.js` (Vitest-via-the-terminal package can pick them up if needed). The repo currently has no extension-specific tests; add them if you change message-passing logic.
- Update root CHANGELOG.md on any user-visible change.
- Branch: main (pre-release, all commits to main).
