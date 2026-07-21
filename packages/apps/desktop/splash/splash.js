// First-run bootstrap progress. The shell emits "bootstrap://status" events
// ({phase, pct, message}) while it downloads and verifies the backend payload;
// this page renders them and offers a Retry action when an attempt fails.
(function () {
  var internals = window.__TAURI_INTERNALS__;
  var statusEl = document.getElementById("status");
  var progressEl = document.getElementById("progress");
  var fillEl = document.getElementById("progress-fill");
  var errorEl = document.getElementById("error");
  var errorMessageEl = document.getElementById("error-message");
  var retryEl = document.getElementById("retry");
  if (!internals || !statusEl || !progressEl || !fillEl || !errorEl || !errorMessageEl || !retryEl) {
    return;
  }
  var sawLiveEvent = false;

  function showStatus(message) {
    document.body.classList.remove("errored");
    errorEl.classList.remove("visible");
    statusEl.textContent = message;
  }

  function showError(message) {
    document.body.classList.add("errored");
    errorMessageEl.textContent = message || "The trading engine could not be prepared.";
    errorEl.classList.add("visible");
    retryEl.disabled = false;
  }

  function render(status) {
    if (!status || typeof status.phase !== "string") {
      return;
    }
    if (status.phase === "error") {
      showError(status.message);
      return;
    }
    showStatus(status.message || "Starting engine");
    if (typeof status.pct === "number") {
      progressEl.classList.add("visible");
      fillEl.style.width = Math.max(0, Math.min(100, status.pct)) + "%";
    }
    if (status.phase === "starting") {
      progressEl.classList.remove("visible");
    }
  }

  retryEl.addEventListener("click", function () {
    retryEl.disabled = true;
    showStatus("Retrying...");
    internals.invoke("retry_bootstrap").catch(function (error) {
      showError(String(error));
    });
  });

  internals
    .invoke("plugin:event|listen", {
      event: "bootstrap://status",
      target: { kind: "Any" },
      handler: internals.transformCallback(function (event) {
        sawLiveEvent = true;
        render(event && event.payload);
      }),
    })
    .catch(function () {
      // The poll below is the ground truth; the listener is only the
      // low-latency fast path.
    });

  // Ground-truth poll. v0.6.0-beta.4 relied on events alone and a
  // label-targeted emit never reached this page's Any-target listener, so the
  // splash froze on "Starting engine..." for the entire payload download.
  var lastRendered = "";
  setInterval(function () {
    internals
      .invoke("bootstrap_status")
      .then(function (status) {
        if (!status || sawLiveEvent) return;
        var key = JSON.stringify(status);
        if (key === lastRendered) return;
        lastRendered = key;
        render(status);
      })
      .catch(function () {
        // Keep whatever is on screen; the next tick retries.
      });
  }, 700);
})();
