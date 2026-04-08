/**
 * FlintTrade Chrome Extension — Content Script
 *
 * Runs on NSE India and Moneycontrol pages. Detects stock symbols and adds
 * a "Trade on FlintTrade" button next to them.
 */

(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // Symbol detection patterns
  // ---------------------------------------------------------------------------

  // NSE symbol format: uppercase letters, possibly with digits and hyphens
  // e.g. RELIANCE, NIFTY, BANKNIFTY, TCS, INFY, TATAMOTORS
  const NSE_SYMBOL_REGEX = /\b([A-Z]{2,}(?:[A-Z0-9&-]*[A-Z])?)\b/g;

  // Known NSE symbols to validate against (top 50 — extendable)
  const KNOWN_SYMBOLS = new Set([
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "HINDUNILVR",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "ITC", "LT", "AXISBANK",
    "BAJFINANCE", "ASIANPAINT", "MARUTI", "TITAN", "SUNPHARMA",
    "ULTRACEMCO", "NESTLEIND", "WIPRO", "HCLTECH", "POWERGRID",
    "NTPC", "ONGC", "TATAMOTORS", "JSWSTEEL", "TATASTEEL", "ADANIENT",
    "ADANIPORTS", "BAJAJFINSV", "TECHM", "INDUSINDBK", "CIPLA",
    "GRASIM", "DRREDDY", "DIVISLAB", "APOLLOHOSP", "EICHERMOT",
    "HEROMOTOCO", "HINDALCO", "BPCL", "COALINDIA", "BRITANNIA",
    "SBILIFE", "HDFCLIFE", "NIFTY", "BANKNIFTY", "FINNIFTY",
    "SENSEX", "NIFTYIT",
  ]);

  // Track which elements we've already processed to avoid duplicates
  const processedElements = new WeakSet();

  // Store the last detected symbol for popup communication
  let lastDetectedSymbol = "";

  // ---------------------------------------------------------------------------
  // Button injection
  // ---------------------------------------------------------------------------

  /**
   * Create a "Trade on FlintTrade" button element.
   * @param {string} symbol - The stock symbol
   * @returns {HTMLButtonElement}
   */
  function createTradeButton(symbol) {
    const btn = document.createElement("button");
    btn.className = "flinttrade-trade-btn";
    btn.textContent = "Trade";
    btn.title = `Trade ${symbol} on FlintTrade`;
    btn.dataset.ftSymbol = symbol;

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      lastDetectedSymbol = symbol;

      // Open the extension popup with the symbol pre-filled
      // Since we cannot programmatically open the popup, store the symbol
      // and let the popup read it
      chrome.storage.local.set({ ft_last_symbol: symbol });

      // Also try sending a message to the popup if it's open
      chrome.runtime.sendMessage({
        action: "symbolSelected",
        symbol: symbol,
      }).catch(() => {
        // Popup not open — that's fine, symbol is stored
      });
    });

    return btn;
  }

  /**
   * Scan a DOM element for stock symbols and inject trade buttons.
   * @param {HTMLElement} root - The root element to scan
   */
  function scanForSymbols(root) {
    // Target elements that likely contain stock names
    const selectors = [
      // NSE India
      'a[href*="/get-quotes/"]',
      'td[data-th="Symbol"]',
      ".symbol-word",
      // Moneycontrol
      'a[href*="/stockpricequote/"]',
      ".stock_name",
      ".company_name a",
      ".FL a",
      // Generic: table cells and links with uppercase text
      "td a",
      "h1",
      "h2",
    ];

    const elements = root.querySelectorAll(selectors.join(", "));

    for (const el of elements) {
      if (processedElements.has(el)) continue;

      const text = (el.textContent || "").trim();
      if (!text || text.length > 30) continue;

      // Check if the text matches a known symbol
      const matches = text.match(NSE_SYMBOL_REGEX);
      if (!matches) continue;

      for (const match of matches) {
        if (KNOWN_SYMBOLS.has(match) && match.length >= 2) {
          processedElements.add(el);

          // Only add button if one doesn't exist already
          if (!el.parentElement?.querySelector(".flinttrade-trade-btn")) {
            const btn = createTradeButton(match);
            el.parentElement?.insertBefore(btn, el.nextSibling);
          }
          break; // One button per element
        }
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Communication with popup
  // ---------------------------------------------------------------------------

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.action === "getSelectedSymbol") {
      // Check storage for the last selected symbol first
      chrome.storage.local.get("ft_last_symbol", (data) => {
        sendResponse({
          symbol: data.ft_last_symbol || lastDetectedSymbol || "",
        });
      });
      return true; // Keep message channel open for async response
    }
  });

  // ---------------------------------------------------------------------------
  // Initialisation
  // ---------------------------------------------------------------------------

  // Initial scan after DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => scanForSymbols(document.body));
  } else {
    scanForSymbols(document.body);
  }

  // Observe DOM changes for dynamically loaded content (SPAs)
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE) {
          scanForSymbols(node);
        }
      }
    }
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
  });
})();
