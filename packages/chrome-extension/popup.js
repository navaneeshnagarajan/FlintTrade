/**
 * FlintTrade Chrome Extension — Popup Script
 *
 * Handles connection to FlintTrade, quick order placement, signal display,
 * and LE/LX/SE/SX button bar settings.
 */

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const DEFAULT_HOST = "http://localhost:5173";
const STORAGE_KEYS = { host: "ft_host", apiKey: "ft_api_key" };
const ORDER_KEYS = {
  symbol: "ft_order_symbol",
  exchange: "ft_order_exchange",
  qty: "ft_order_qty",
  product: "ft_order_product",
};
const BAR_VISIBLE_KEY = "ft_button_bar_visible";

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const statusEl = document.getElementById("connection-status");
const statusTextEl = statusEl.querySelector(".status-text");
const hostInput = document.getElementById("host-input");
const apiKeyInput = document.getElementById("apikey-input");
const saveSettingsBtn = document.getElementById("save-settings");
const settingsToggle = document.getElementById("settings-toggle");
const settingsForm = document.getElementById("settings-form");
const symbolInput = document.getElementById("symbol-input");
const exchangeInput = document.getElementById("exchange-input");
const qtyInput = document.getElementById("qty-input");
const buyBtn = document.getElementById("buy-btn");
const sellBtn = document.getElementById("sell-btn");
const orderResult = document.getElementById("order-result");
const signalsList = document.getElementById("signals-list");

// Order settings for button bar
const orderSymbolInput = document.getElementById("order-symbol");
const orderExchangeInput = document.getElementById("order-exchange");
const orderQtyInput = document.getElementById("order-qty");
const orderProductInput = document.getElementById("order-product");
const saveOrderSettingsBtn = document.getElementById("save-order-settings");

// Bar toggle
const barToggle = document.getElementById("bar-toggle");

// ---------------------------------------------------------------------------
// Settings persistence (chrome.storage.local)
// ---------------------------------------------------------------------------

async function loadSettings() {
  return new Promise((resolve) => {
    chrome.storage.local.get(
      [STORAGE_KEYS.host, STORAGE_KEYS.apiKey],
      (data) => {
        resolve({
          host: data[STORAGE_KEYS.host] || DEFAULT_HOST,
          apiKey: data[STORAGE_KEYS.apiKey] || "",
        });
      }
    );
  });
}

async function saveSettings(host, apiKey) {
  return new Promise((resolve) => {
    chrome.storage.local.set(
      { [STORAGE_KEYS.host]: host, [STORAGE_KEYS.apiKey]: apiKey },
      resolve
    );
  });
}

async function loadOrderSettings() {
  return new Promise((resolve) => {
    chrome.storage.local.get(
      [ORDER_KEYS.symbol, ORDER_KEYS.exchange, ORDER_KEYS.qty, ORDER_KEYS.product],
      (data) => {
        resolve({
          symbol: data[ORDER_KEYS.symbol] || "",
          exchange: data[ORDER_KEYS.exchange] || "NSE",
          qty: data[ORDER_KEYS.qty] || "1",
          product: data[ORDER_KEYS.product] || "MIS",
        });
      }
    );
  });
}

async function saveOrderSettings(symbol, exchange, qty, product) {
  return new Promise((resolve) => {
    chrome.storage.local.set(
      {
        [ORDER_KEYS.symbol]: symbol,
        [ORDER_KEYS.exchange]: exchange,
        [ORDER_KEYS.qty]: qty,
        [ORDER_KEYS.product]: product,
      },
      resolve
    );
  });
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function ftFetch(settings, endpoint, method = "GET", body = null) {
  const url = `${settings.host}/ft-api/api/v1/${endpoint}`;
  const headers = { "Content-Type": "application/json" };
  if (settings.apiKey) {
    headers["X-API-Key"] = settings.apiKey;
  }
  const opts = { method, headers };
  if (body) {
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(url, opts);
  if (!resp.ok) {
    const errBody = await resp.json().catch(() => null);
    throw new Error(
      errBody?.message || errBody?.error || `HTTP ${resp.status}`
    );
  }
  const json = await resp.json();
  if (json.status === "error") {
    throw new Error(json.message || "API error");
  }
  return json.data ?? json;
}

// ---------------------------------------------------------------------------
// Connection check
// ---------------------------------------------------------------------------

async function checkConnection(settings) {
  try {
    const url = `${settings.host}/api/v1/ping`;
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apikey: settings.apiKey }),
    });
    if (resp.ok) {
      setConnected(true);
      return true;
    }
  } catch {
    // Connection failed
  }
  setConnected(false);
  return false;
}

function setConnected(connected) {
  statusEl.className = connected
    ? "status connected"
    : "status disconnected";
  statusTextEl.textContent = connected ? "Connected" : "Disconnected";
}

// ---------------------------------------------------------------------------
// Order placement
// ---------------------------------------------------------------------------

async function placeOrder(action, settings) {
  const symbol = symbolInput.value.trim().toUpperCase();
  const exchange = exchangeInput.value;
  const qty = parseInt(qtyInput.value, 10);

  if (!symbol) {
    showResult("Enter a symbol", "error");
    return;
  }
  if (!qty || qty < 1) {
    showResult("Enter a valid quantity", "error");
    return;
  }

  try {
    const result = await ftFetch(settings, "orders/place", "POST", {
      symbol,
      exchange,
      action,
      quantity: qty,
      order_type: "MARKET",
      product: "MIS",
      price_type: "MARKET",
    });
    showResult(
      `${action} order placed: ${symbol} x${qty} (${result.orderId || "OK"})`,
      "success"
    );
  } catch (err) {
    showResult(`Order failed: ${err.message}`, "error");
  }
}

function showResult(message, type) {
  orderResult.textContent = message;
  orderResult.className = `result ${type}`;
}

// ---------------------------------------------------------------------------
// Signals
// ---------------------------------------------------------------------------

async function loadSignals(settings) {
  try {
    const data = await ftFetch(settings, "signals/recent?limit=5");
    const signals = data.signals || [];
    if (signals.length === 0) {
      signalsList.innerHTML = '<p class="muted">No recent signals</p>';
      return;
    }
    signalsList.innerHTML = signals
      .map((s) => {
        const typeClass = s.signal_type === "BUY" ? "buy" : s.signal_type === "SELL" ? "sell" : "alert";
        const time = new Date(s.timestamp).toLocaleTimeString("en-IN", {
          hour: "2-digit",
          minute: "2-digit",
        });
        return `
          <div class="signal-item">
            <span class="signal-symbol">${s.symbol}</span>
            <span class="signal-type ${typeClass}">${s.signal_type}</span>
            <span class="signal-time">${time}</span>
          </div>
        `;
      })
      .join("");
  } catch {
    signalsList.innerHTML =
      '<p class="muted">Could not load signals</p>';
  }
}

// ---------------------------------------------------------------------------
// Bar toggle
// ---------------------------------------------------------------------------

function toggleButtonBar(visible) {
  chrome.storage.local.set({ [BAR_VISIBLE_KEY]: visible });
  // Send message to content script to show/hide
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.id) {
      chrome.tabs.sendMessage(tabs[0].id, { action: "toggleButtonBar" }).catch(() => {});
    }
  });
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  const settings = await loadSettings();
  hostInput.value = settings.host;
  apiKeyInput.value = settings.apiKey;

  // Load order settings for button bar
  const orderSettings = await loadOrderSettings();
  orderSymbolInput.value = orderSettings.symbol;
  orderExchangeInput.value = orderSettings.exchange;
  orderQtyInput.value = orderSettings.qty;
  orderProductInput.value = orderSettings.product;

  // Load bar visibility
  chrome.storage.local.get(BAR_VISIBLE_KEY, (data) => {
    barToggle.checked = data[BAR_VISIBLE_KEY] !== false;
  });

  // Check connection
  const connected = await checkConnection(settings);
  if (connected) {
    loadSignals(settings);
  }

  // Pre-fill symbol from content script message (if any)
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.id) {
      chrome.tabs.sendMessage(
        tabs[0].id,
        { action: "getSelectedSymbol" },
        (response) => {
          if (chrome.runtime.lastError) return;
          if (response?.symbol) {
            symbolInput.value = response.symbol;
          }
        }
      );
    }
  });

  // Settings toggle
  settingsToggle.addEventListener("click", () => {
    const isHidden = settingsForm.classList.contains("hidden");
    settingsForm.classList.toggle("hidden");
    settingsToggle.innerHTML = isHidden
      ? "Connection &#9652;"
      : "Connection &#9662;";
  });

  // Save connection settings
  saveSettingsBtn.addEventListener("click", async () => {
    const newHost = hostInput.value.trim() || DEFAULT_HOST;
    const newKey = apiKeyInput.value.trim();
    await saveSettings(newHost, newKey);
    const newSettings = { host: newHost, apiKey: newKey };
    const conn = await checkConnection(newSettings);
    if (conn) loadSignals(newSettings);
  });

  // Save order settings for button bar
  saveOrderSettingsBtn.addEventListener("click", async () => {
    const sym = orderSymbolInput.value.trim().toUpperCase();
    const exch = orderExchangeInput.value;
    const qty = orderQtyInput.value || "1";
    const prod = orderProductInput.value;
    await saveOrderSettings(sym, exch, qty, prod);
    orderSymbolInput.value = sym;
    showResult("Order settings saved", "success");
  });

  // Bar toggle
  barToggle.addEventListener("change", () => {
    toggleButtonBar(barToggle.checked);
  });

  // Order buttons
  buyBtn.addEventListener("click", () => placeOrder("BUY", settings));
  sellBtn.addEventListener("click", () => placeOrder("SELL", settings));
});
