/**
 * FlintTrade Chrome Extension — Popup Script
 *
 * Handles connection to FlintTrade, quick order placement, and signal display.
 */

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const DEFAULT_HOST = "http://localhost:5173";
const STORAGE_KEYS = { host: "ft_host", apiKey: "ft_api_key" };

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
    // Use the OpenAlgo ping endpoint via FlintTrade proxy
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
    // Place order via the FlintTrade safety proxy
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
// Init
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  const settings = await loadSettings();
  hostInput.value = settings.host;
  apiKeyInput.value = settings.apiKey;

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
          if (chrome.runtime.lastError) return; // content script not injected
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
      ? "Settings &#9652;"
      : "Settings &#9662;";
  });

  // Save settings
  saveSettingsBtn.addEventListener("click", async () => {
    const newHost = hostInput.value.trim() || DEFAULT_HOST;
    const newKey = apiKeyInput.value.trim();
    await saveSettings(newHost, newKey);
    const newSettings = { host: newHost, apiKey: newKey };
    const conn = await checkConnection(newSettings);
    if (conn) loadSignals(newSettings);
  });

  // Order buttons
  buyBtn.addEventListener("click", () => placeOrder("BUY", settings));
  sellBtn.addEventListener("click", () => placeOrder("SELL", settings));
});
