/**
 * FlintTrade Chrome Extension — Content Script
 *
 * Runs on all webpages. Provides two features:
 *   1. Symbol detection on NSE/Moneycontrol (existing)
 *   2. Draggable floating LE/LX/SE/SX button bar for quick trading
 */

(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // Symbol detection patterns (NSE/Moneycontrol only)
  // ---------------------------------------------------------------------------

  const NSE_SYMBOL_REGEX = /\b([A-Z]{2,}(?:[A-Z0-9&-]*[A-Z])?)\b/g;

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

  const processedElements = new WeakSet();
  let lastDetectedSymbol = "";

  // ---------------------------------------------------------------------------
  // Symbol detection — Trade button injection
  // ---------------------------------------------------------------------------

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
      chrome.storage.local.set({ ft_last_symbol: symbol });
      chrome.runtime.sendMessage({
        action: "symbolSelected",
        symbol: symbol,
      }).catch(() => {});
    });

    return btn;
  }

  function scanForSymbols(root) {
    const selectors = [
      'a[href*="/get-quotes/"]',
      'td[data-th="Symbol"]',
      ".symbol-word",
      'a[href*="/stockpricequote/"]',
      ".stock_name",
      ".company_name a",
      ".FL a",
      "td a",
      "h1",
      "h2",
    ];

    const elements = root.querySelectorAll(selectors.join(", "));

    for (const el of elements) {
      if (processedElements.has(el)) continue;

      const text = (el.textContent || "").trim();
      if (!text || text.length > 30) continue;

      const matches = text.match(NSE_SYMBOL_REGEX);
      if (!matches) continue;

      for (const match of matches) {
        if (KNOWN_SYMBOLS.has(match) && match.length >= 2) {
          processedElements.add(el);
          if (!el.parentElement?.querySelector(".flinttrade-trade-btn")) {
            const btn = createTradeButton(match);
            el.parentElement?.insertBefore(btn, el.nextSibling);
          }
          break;
        }
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Floating LE/LX/SE/SX Button Bar
  // ---------------------------------------------------------------------------

  const STORAGE_POS_KEY = "ft_button_bar_position";
  const STORAGE_VISIBLE_KEY = "ft_button_bar_visible";

  /**
   * Inject the draggable floating trading button bar.
   */
  function injectButtonBar() {
    if (document.getElementById("ft-button-bar")) return;

    const container = document.createElement("div");
    container.id = "ft-button-bar";
    container.className = "ft-button-bar";

    // Drag handle
    const handle = document.createElement("div");
    handle.className = "ft-bar-handle";
    handle.title = "Drag to move";
    container.appendChild(handle);

    // Buttons: LE (green), LX (red), SE (red), SX (green)
    const buttons = [
      { id: "ft-le", text: "LE", cls: "ft-btn-green", tooltip: "Long Entry (Buy)", action: "longEntry" },
      { id: "ft-lx", text: "LX", cls: "ft-btn-red", tooltip: "Long Exit (Sell)", action: "longExit" },
      { id: "ft-se", text: "SE", cls: "ft-btn-red", tooltip: "Short Entry (Sell)", action: "shortEntry" },
      { id: "ft-sx", text: "SX", cls: "ft-btn-green", tooltip: "Short Exit (Buy)", action: "shortExit" },
    ];

    const btnRow = document.createElement("div");
    btnRow.className = "ft-bar-buttons";

    for (const b of buttons) {
      const btn = document.createElement("button");
      btn.id = b.id;
      btn.textContent = b.text;
      btn.className = `ft-bar-btn ${b.cls}`;
      btn.title = b.tooltip;
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        handleOrderClick(b.action);
      });
      btnRow.appendChild(btn);
    }

    container.appendChild(btnRow);

    // Restore position from localStorage
    const savedPos = localStorage.getItem(STORAGE_POS_KEY);
    if (savedPos) {
      try {
        const { x, y } = JSON.parse(savedPos);
        container.style.left = `${x}px`;
        container.style.top = `${y}px`;
      } catch {
        container.style.top = "80px";
        container.style.right = "20px";
      }
    } else {
      container.style.top = "80px";
      container.style.right = "20px";
    }

    makeDraggable(container, handle);
    document.body.appendChild(container);

    // Check visibility preference
    chrome.storage.local.get(STORAGE_VISIBLE_KEY, (data) => {
      if (data[STORAGE_VISIBLE_KEY] === false) {
        container.style.display = "none";
      }
    });
  }

  /**
   * Make the container draggable via the handle, saving position to localStorage.
   */
  function makeDraggable(container, handle) {
    let isDragging = false;
    let offsetX = 0;
    let offsetY = 0;

    handle.addEventListener("mousedown", (e) => {
      isDragging = true;
      offsetX = e.clientX - container.getBoundingClientRect().left;
      offsetY = e.clientY - container.getBoundingClientRect().top;
      // Reset right positioning so left works cleanly
      container.style.right = "auto";
      e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      const x = Math.max(0, Math.min(window.innerWidth - 180, e.clientX - offsetX));
      const y = Math.max(0, Math.min(window.innerHeight - 40, e.clientY - offsetY));
      container.style.left = `${x}px`;
      container.style.top = `${y}px`;
    });

    document.addEventListener("mouseup", () => {
      if (!isDragging) return;
      isDragging = false;
      // Save position
      const rect = container.getBoundingClientRect();
      localStorage.setItem(STORAGE_POS_KEY, JSON.stringify({ x: rect.left, y: rect.top }));
    });
  }

  /**
   * Handle LE/LX/SE/SX button click — reads settings from chrome.storage and
   * sends the order to OpenAlgo (or FlintTrade).
   */
  function handleOrderClick(action) {
    chrome.storage.local.get(
      ["ft_host", "ft_api_key", "ft_order_symbol", "ft_order_exchange", "ft_order_qty", "ft_order_product"],
      (settings) => {
        const host = settings.ft_host || "http://localhost:5173";
        const apiKey = settings.ft_api_key || "";
        const symbol = settings.ft_order_symbol || "";
        const exchange = settings.ft_order_exchange || "NSE";
        const qty = settings.ft_order_qty || "1";
        const product = settings.ft_order_product || "MIS";

        if (!symbol) {
          showNotification("Set a symbol in the extension popup first", "error");
          return;
        }
        if (!apiKey) {
          showNotification("Set an API key in the extension popup first", "error");
          return;
        }

        let apiAction = "";
        let orderType = "regular"; // "regular" = placeorder, "smart" = placesmartorder

        switch (action) {
          case "longEntry":
            apiAction = "BUY";
            orderType = "regular";
            break;
          case "longExit":
            apiAction = "SELL";
            orderType = "smart";
            break;
          case "shortEntry":
            apiAction = "SELL";
            orderType = "regular";
            break;
          case "shortExit":
            apiAction = "BUY";
            orderType = "smart";
            break;
        }

        const actionLabel = {
          longEntry: "Long Entry",
          longExit: "Long Exit",
          shortEntry: "Short Entry",
          shortExit: "Short Exit",
        }[action];

        const endpoint = orderType === "smart" ? "placesmartorder" : "placeorder";
        const url = `${host}/api/v1/${endpoint}`;

        const body = orderType === "smart"
          ? {
              apikey: apiKey,
              strategy: "FlintChrome",
              symbol,
              action: apiAction,
              exchange,
              pricetype: "MARKET",
              product,
              quantity: "0",
              position_size: "0",
            }
          : {
              apikey: apiKey,
              strategy: "FlintChrome",
              symbol,
              action: apiAction,
              exchange,
              pricetype: "MARKET",
              product,
              quantity: qty,
            };

        showNotification(`${actionLabel}: ${symbol}...`, "info");

        fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        })
          .then((r) => r.json())
          .then((data) => {
            if (data.status === "success") {
              showNotification(`${actionLabel} successful`, "success");
            } else {
              showNotification(`${actionLabel} failed: ${data.message || "Unknown error"}`, "error");
            }
          })
          .catch((err) => {
            showNotification(`API error: ${err.message}`, "error");
          });
      },
    );
  }

  /**
   * Display a brief notification toast in the bottom-right corner.
   */
  function showNotification(message, type) {
    const el = document.createElement("div");
    el.className = `ft-notification ft-notification-${type}`;
    el.textContent = message;
    document.body.appendChild(el);

    setTimeout(() => {
      el.classList.add("ft-notification-fade");
      setTimeout(() => el.remove(), 400);
    }, 3000);
  }

  // ---------------------------------------------------------------------------
  // Communication with popup
  // ---------------------------------------------------------------------------

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.action === "getSelectedSymbol") {
      chrome.storage.local.get("ft_last_symbol", (data) => {
        sendResponse({
          symbol: data.ft_last_symbol || lastDetectedSymbol || "",
        });
      });
      return true;
    }

    if (message.action === "toggleButtonBar") {
      const bar = document.getElementById("ft-button-bar");
      if (bar) {
        const isVisible = bar.style.display !== "none";
        bar.style.display = isVisible ? "none" : "flex";
        chrome.storage.local.set({ [STORAGE_VISIBLE_KEY]: !isVisible });
      }
      sendResponse({ success: true });
      return true;
    }
  });

  // ---------------------------------------------------------------------------
  // CSS injection
  // ---------------------------------------------------------------------------

  function injectStyles() {
    const style = document.createElement("style");
    style.textContent = `
      /* --- Floating LE/LX/SE/SX Button Bar --- */
      .ft-button-bar {
        position: fixed;
        z-index: 99999;
        display: flex;
        align-items: center;
        gap: 2px;
        padding: 3px 4px 3px 2px;
        background: rgba(20, 20, 26, 0.95);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 6px;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        backdrop-filter: blur(8px);
      }

      .ft-bar-handle {
        width: 6px;
        height: 28px;
        border-radius: 3px;
        background: rgba(255, 255, 255, 0.15);
        cursor: grab;
        flex-shrink: 0;
        margin-right: 2px;
      }

      .ft-bar-handle:active {
        cursor: grabbing;
        background: rgba(255, 255, 255, 0.3);
      }

      .ft-bar-buttons {
        display: flex;
        gap: 3px;
      }

      .ft-bar-btn {
        min-width: 32px;
        height: 28px;
        padding: 0 8px;
        border: none;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.5px;
        cursor: pointer;
        transition: transform 0.1s, box-shadow 0.15s, opacity 0.15s;
        color: #fff;
        text-transform: uppercase;
      }

      .ft-bar-btn:hover {
        transform: translateY(-1px);
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
      }

      .ft-bar-btn:active {
        transform: scale(0.95);
      }

      .ft-btn-green {
        background: #22c55e;
      }

      .ft-btn-green:hover {
        background: #16a34a;
      }

      .ft-btn-red {
        background: #ef4444;
      }

      .ft-btn-red:hover {
        background: #dc2626;
      }

      /* --- Notifications --- */
      .ft-notification {
        position: fixed;
        bottom: 16px;
        right: 16px;
        z-index: 100000;
        padding: 8px 14px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        color: #fff;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        animation: ft-slide-in 0.2s ease;
        max-width: 280px;
        word-break: break-word;
      }

      .ft-notification-success { background: #22c55e; }
      .ft-notification-error { background: #ef4444; }
      .ft-notification-info { background: #3b82f6; }

      .ft-notification-fade {
        opacity: 0;
        transform: translateX(10px);
        transition: opacity 0.4s, transform 0.4s;
      }

      @keyframes ft-slide-in {
        from { opacity: 0; transform: translateX(10px); }
        to { opacity: 1; transform: translateX(0); }
      }

      /* --- Existing: Trade button on symbol detection --- */
      .flinttrade-trade-btn {
        display: inline-flex;
        align-items: center;
        margin-left: 6px;
        padding: 2px 8px;
        background: #6366f1;
        color: #fff;
        border: none;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 600;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        cursor: pointer;
        transition: opacity 0.15s, transform 0.1s;
        vertical-align: middle;
        line-height: 1.4;
      }

      .flinttrade-trade-btn:hover {
        opacity: 0.85;
        transform: scale(1.02);
      }

      .flinttrade-trade-btn:active {
        transform: scale(0.97);
      }
    `;
    document.head.appendChild(style);
  }

  // ---------------------------------------------------------------------------
  // Initialisation
  // ---------------------------------------------------------------------------

  injectStyles();

  // Symbol detection (only on financial sites)
  const isFinancialSite =
    location.hostname.includes("nseindia.com") ||
    location.hostname.includes("moneycontrol.com");

  if (isFinancialSite) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => scanForSymbols(document.body));
    } else {
      scanForSymbols(document.body);
    }

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            scanForSymbols(node);
          }
        }
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
  }

  // Floating button bar — injected on all pages
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectButtonBar);
  } else {
    injectButtonBar();
  }
})();
