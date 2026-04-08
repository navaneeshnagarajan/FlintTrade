# FlintTrade Chrome Extension

Quick trade from any webpage. Companion extension for FlintTrade.

## Features

- **Popup:** Connection status, quick order form, recent signals
- **Content Script:** Detects stock symbols on NSE India and Moneycontrol pages, adds "Trade" buttons

## Installation (Developer Mode)

1. Open Chrome and navigate to `chrome://extensions/`
2. Enable **Developer mode** (toggle in the top-right corner)
3. Click **Load unpacked**
4. Select the `packages/chrome-extension/` directory
5. The extension icon should appear in your toolbar

## Configuration

1. Click the FlintTrade extension icon
2. Click **Settings** to expand the settings panel
3. Enter your FlintTrade host (default: `http://localhost:5173`)
4. Enter your API key
5. Click **Save**

## Supported Sites

- [NSE India](https://www.nseindia.com/) — detects symbols on quote pages
- [Moneycontrol](https://www.moneycontrol.com/) — detects symbols on stock pages

## Icons

Place icon files in the `icons/` directory:
- `icon-16.png` (16x16)
- `icon-48.png` (48x48)
- `icon-128.png` (128x128)

You can generate these from the FlintTrade logo SVG.

## Development

This is a scaffold (v0.1.0). Planned improvements:

- [ ] Proper icon assets
- [ ] Background service worker for persistent connection
- [ ] Real-time price display in popup
- [ ] Keyboard shortcuts for quick orders
- [ ] Support more financial sites (Screener.in, Tickertape, etc.)
- [ ] Options quick-order form
- [ ] Position summary in popup
