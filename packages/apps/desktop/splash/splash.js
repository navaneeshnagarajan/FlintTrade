// Adapted from NousResearch/hermes-agent commit 7651764ce (MIT).
// Local splash and recovery renderer. Machine authority remains behind the
// named, sandboxed window.flintDesktop preload bridge.
(function () {
  "use strict";

  var bridge = window.flintDesktop;
  var body = document.body;
  var statusEl = document.getElementById("status");
  var phaseEl = document.getElementById("phase");
  var progressEl = document.getElementById("progress");
  var fillEl = document.getElementById("progress-fill");
  var errorEl = document.getElementById("error");
  var errorMessageEl = document.getElementById("error-message");
  var actionsEl = document.getElementById("actions");
  var actionStatusEl = document.getElementById("action-status");
  var retryEl = document.getElementById("retry");
  var cancelEl = document.getElementById("cancel");
  var quitEl = document.getElementById("quit");

  if (
    !bridge ||
    !body ||
    !statusEl ||
    !phaseEl ||
    !progressEl ||
    !fillEl ||
    !errorEl ||
    !errorMessageEl ||
    !actionsEl ||
    !actionStatusEl ||
    !retryEl ||
    !cancelEl ||
    !quitEl
  ) {
    return;
  }

  var bootstrapSnapshot = null;
  var backendSnapshot = null;
  var latestBootstrapAttempt = -1;
  var latestBootstrapHeartbeat = -1;
  var bootstrapPublicationReceivedAt = 0;
  var lockedBootstrapAttempt = null;
  var backendFailureLocked = false;
  var backendCancelRequested = false;
  var backendRetryPending = false;
  var backendEventVersion = 0;
  var backendPollVersion = 0;
  var retryPending = false;
  var retryRequestInFlight = false;
  var cancelPending = false;
  var cancelRequestInFlight = false;
  var cancelConfirmed = false;
  var quitPending = false;
  var heartbeatKey = "";
  var heartbeatBase = "";
  var heartbeatTicks = 0;
  var heartbeatActive = false;
  var disposed = false;
  var BOOTSTRAP_HEARTBEAT_STALE_MS = 4_000;

  function isBootstrapSnapshot(snapshot) {
    return (
      snapshot &&
      Number.isSafeInteger(snapshot.attempt) &&
      snapshot.attempt >= 0 &&
      typeof snapshot.heartbeatAt === "number" &&
      Number.isFinite(snapshot.heartbeatAt) &&
      typeof snapshot.message === "string" &&
      typeof snapshot.phase === "string" &&
      (snapshot.status === "idle" ||
        snapshot.status === "running" ||
        snapshot.status === "ready" ||
        snapshot.status === "failed")
    );
  }

  function isBackendSnapshot(snapshot) {
    return (
      snapshot &&
      (snapshot.status === "stopped" ||
        snapshot.status === "starting" ||
        snapshot.status === "ready" ||
        snapshot.status === "failed")
    );
  }

  function isSameBootstrapPublication(left, right) {
    return Boolean(
      left &&
      right &&
      left.attempt === right.attempt &&
      left.failure === right.failure &&
      left.heartbeatAt === right.heartbeatAt &&
      left.message === right.message &&
      left.phase === right.phase &&
      left.progress === right.progress &&
      left.status === right.status
    );
  }

  function phaseLabel(phase) {
    var labels = {
      "building-terminal": "Building terminal",
      cancelled: "Cancelled",
      "checking-source": "Checking source",
      "cloning-source": "Cloning source",
      complete: "Source ready",
      failed: "Setup failed",
      idle: "Waiting",
      "installing-tools": "Installing local tools",
      preparing: "Preparing",
      "starting-backend": "Starting backend",
      "syncing-javascript": "Installing terminal dependencies",
      "syncing-python": "Installing Python dependencies",
    };
    return labels[phase] || "Preparing FlintTrade";
  }

  function setButtonVisible(button, visible) {
    if (visible) button.classList.add("visible");
    else button.classList.remove("visible");
  }

  function setProgress(progress, indeterminate) {
    progressEl.classList.remove("visible", "indeterminate");
    progressEl.removeAttribute("aria-valuenow");
    if (indeterminate) {
      progressEl.classList.add("visible", "indeterminate");
      fillEl.style.width = "35%";
      progressEl.setAttribute("aria-valuetext", "In progress");
      return;
    }
    if (typeof progress !== "number" || !Number.isFinite(progress)) {
      fillEl.style.width = "0%";
      progressEl.setAttribute("aria-valuetext", "Progress unavailable");
      return;
    }
    var bounded = Math.max(0, Math.min(100, progress));
    progressEl.classList.add("visible");
    fillEl.style.width = bounded + "%";
    progressEl.setAttribute("aria-valuenow", String(bounded));
    progressEl.setAttribute("aria-valuetext", bounded + "% complete");
  }

  function setHeartbeat(key, base, active) {
    if (heartbeatKey !== key) {
      heartbeatKey = key;
      heartbeatTicks = 0;
    }
    heartbeatBase = base;
    heartbeatActive = active;
    statusEl.textContent = heartbeatTicks > 0
      ? heartbeatBase + " · still working · " + heartbeatTicks * 4 + "s"
      : heartbeatBase;
  }

  function clearActionStatus() {
    actionStatusEl.textContent = "";
  }

  function clearConfirmedCancellationIfSettled() {
    var bootstrapSettled = Boolean(bootstrapSnapshot && bootstrapSnapshot.status === "failed");
    var backendSettled = Boolean(
      backendFailureLocked &&
      backendSnapshot &&
      (backendSnapshot.status === "failed" || backendSnapshot.status === "stopped")
    );
    if (!cancelConfirmed || (!bootstrapSettled && !backendSettled)) return false;
    cancelConfirmed = false;
    cancelPending = false;
    clearActionStatus();
    return true;
  }

  function showBootstrapStallIfNeeded() {
    if (
      !bootstrapSnapshot ||
      bootstrapSnapshot.status !== "running" ||
      bootstrapPublicationReceivedAt === 0 ||
      Date.now() - bootstrapPublicationReceivedAt <= BOOTSTRAP_HEARTBEAT_STALE_MS
    ) {
      return false;
    }
    heartbeatActive = false;
    phaseEl.textContent = "Startup response delayed";
    statusEl.textContent = "No recent startup progress was received. Waiting for the desktop process…";
    return true;
  }

  function showWorking(options) {
    body.classList.remove("errored");
    errorEl.classList.remove("visible");
    errorMessageEl.textContent = "";
    actionsEl.classList.add("visible");
    setButtonVisible(retryEl, false);
    setButtonVisible(quitEl, false);
    setButtonVisible(cancelEl, options.cancelable);
    retryEl.disabled = false;
    quitEl.disabled = false;
    cancelEl.disabled = cancelPending || cancelRequestInFlight;
    phaseEl.textContent = options.phase;
    setProgress(options.progress, options.indeterminate);
    setHeartbeat(options.key, options.message, options.heartbeat);
  }

  function showError(message, kind) {
    heartbeatActive = false;
    body.classList.add("errored");
    errorEl.classList.add("visible");
    actionsEl.classList.add("visible");
    errorMessageEl.textContent = message || "FlintTrade could not finish starting.";
    phaseEl.textContent = kind === "backend-stopped"
      ? "Trading engine stopped"
      : kind === "backend"
        ? "Trading engine unavailable"
        : "Setup needs attention";
    setProgress(null, false);
    setButtonVisible(cancelEl, false);
    setButtonVisible(retryEl, true);
    setButtonVisible(quitEl, kind === "backend" || kind === "backend-stopped");
    retryEl.disabled = retryPending || retryRequestInFlight || cancelRequestInFlight || quitPending;
    cancelEl.disabled = false;
    quitEl.disabled = quitPending || retryPending || retryRequestInFlight || cancelRequestInFlight;
  }

  function renderCurrent() {
    if (disposed) return;
    if (bootstrapSnapshot && bootstrapSnapshot.status === "failed") {
      showError(
        bootstrapSnapshot.failure || bootstrapSnapshot.message || "FlintTrade setup did not complete.",
        "bootstrap",
      );
      return;
    }

    if (!bootstrapSnapshot || bootstrapSnapshot.status !== "ready") {
      var pending = bootstrapSnapshot;
      var running = pending && pending.status === "running";
      var attempt = pending ? pending.attempt : 0;
      var phase = pending ? pending.phase : "idle";
      var message = pending && pending.message ? pending.message : "Preparing FlintTrade";
      if (running && showBootstrapStallIfNeeded()) return;
      showWorking({
        cancelable: Boolean(running),
        heartbeat: Boolean(running),
        indeterminate: Boolean(running && pending.progress === null),
        key: "bootstrap:" + attempt + ":" + phase + ":" + message,
        message: message,
        phase: phaseLabel(phase),
        progress: pending ? pending.progress : null,
      });
      return;
    }

    if (
      backendFailureLocked &&
      backendSnapshot &&
      (backendSnapshot.status === "failed" || backendSnapshot.status === "stopped")
    ) {
      showError(
        backendCancelRequested && backendSnapshot.status === "stopped"
          ? "Trading-engine startup was cancelled and stopped. Retry when ready, or quit FlintTrade."
          : backendCancelRequested
            ? "Trading-engine startup failed while cancellation was settling. Review the redacted desktop log before retrying or quitting."
          : "The trading engine could not start or became unavailable. Electron will verify cleanup before retry or quit.",
        backendSnapshot.status === "stopped" ? "backend-stopped" : "backend",
      );
      return;
    }

    var backendStatus = backendSnapshot ? backendSnapshot.status : "stopped";
    var backendMessage = "Preparing the trading engine";
    var backendPhase = "Backend preparation";
    var backendHeartbeat = true;
    if (backendStatus === "starting") {
      backendMessage = "Starting the trading engine";
      backendPhase = "Starting backend";
    } else if (backendStatus === "ready") {
      backendMessage = "Opening the FlintTrade terminal";
      backendPhase = "Backend ready";
      backendHeartbeat = false;
    } else if (backendStatus === "stopped") {
      backendMessage = "Preparing the trading engine";
      backendPhase = "Waiting for backend start";
    }
    showWorking({
      cancelable: backendStatus === "starting",
      heartbeat: backendHeartbeat,
      indeterminate: backendStatus !== "ready",
      key: "backend:" + backendStatus,
      message: backendMessage,
      phase: backendPhase,
      progress: backendStatus === "ready" ? 100 : null,
    });
  }

  function acceptBootstrap(snapshot) {
    if (!isBootstrapSnapshot(snapshot) || disposed) return;
    if (isSameBootstrapPublication(bootstrapSnapshot, snapshot)) {
      showBootstrapStallIfNeeded();
      return;
    }
    if (snapshot.attempt < latestBootstrapAttempt) return;
    if (snapshot.attempt === latestBootstrapAttempt && snapshot.heartbeatAt < latestBootstrapHeartbeat) return;
    var alreadyLocked = lockedBootstrapAttempt === snapshot.attempt;
    var containmentEscalation =
      alreadyLocked &&
      bootstrapSnapshot &&
      bootstrapSnapshot.phase === "cancelled" &&
      snapshot.status === "failed" &&
      snapshot.phase === "failed";
    if (alreadyLocked && !containmentEscalation) return;
    if (snapshot.attempt > latestBootstrapAttempt) {
      latestBootstrapAttempt = snapshot.attempt;
      latestBootstrapHeartbeat = -1;
      lockedBootstrapAttempt = null;
      retryPending = false;
      backendRetryPending = false;
      clearActionStatus();
    }
    latestBootstrapHeartbeat = Math.max(latestBootstrapHeartbeat, snapshot.heartbeatAt);
    bootstrapSnapshot = snapshot;
    bootstrapPublicationReceivedAt = Date.now();
    if (containmentEscalation) clearActionStatus();
    if (snapshot.status === "failed") {
      lockedBootstrapAttempt = snapshot.attempt;
      if (!alreadyLocked) {
        retryPending = false;
        cancelPending = false;
        if (snapshot.phase === "cancelled") {
          actionStatusEl.textContent = "Cancellation was requested. Waiting for process settlement.";
        }
      }
    }
    clearConfirmedCancellationIfSettled();
    renderCurrent();
  }

  function acceptBackend(snapshot) {
    if (!isBackendSnapshot(snapshot) || disposed) return;
    var alreadyLocked = backendFailureLocked;
    var cancelledStop = backendCancelRequested && snapshot.status === "stopped";
    if (backendFailureLocked && snapshot.status !== "failed" && !cancelledStop) {
      var recovered = backendRetryPending && (snapshot.status === "starting" || snapshot.status === "ready");
      if (!recovered) return;
      backendFailureLocked = false;
      backendCancelRequested = false;
      backendRetryPending = false;
      retryPending = false;
      clearActionStatus();
    }
    backendSnapshot = snapshot;
    if (snapshot.status === "failed" || cancelledStop) {
      backendFailureLocked = true;
      if (!alreadyLocked) {
        backendRetryPending = false;
        retryPending = false;
        cancelPending = false;
      }
    }
    clearConfirmedCancellationIfSettled();
    renderCurrent();
  }

  function fixedActionFailure(action) {
    actionStatusEl.textContent = action + " could not be requested. Try again or use the tray controls.";
  }

  retryEl.addEventListener("click", async function () {
    if (retryPending || retryRequestInFlight || cancelRequestInFlight || quitPending) return;
    retryPending = true;
    retryRequestInFlight = true;
    backendRetryPending = backendFailureLocked;
    retryEl.disabled = true;
    quitEl.disabled = true;
    actionStatusEl.textContent = "Requesting a fresh start…";
    try {
      var completed = await bridge.retryBootstrap();
      retryRequestInFlight = false;
      if (!completed) {
        retryPending = false;
        backendRetryPending = false;
        retryEl.disabled = false;
        actionStatusEl.textContent = "The restart did not complete. Review the current failure before trying again.";
        renderCurrent();
      } else {
        renderCurrent();
      }
    } catch (_error) {
      retryRequestInFlight = false;
      retryPending = false;
      backendRetryPending = false;
      retryEl.disabled = false;
      fixedActionFailure("Retry");
      renderCurrent();
    }
  });

  cancelEl.addEventListener("click", async function () {
    if (cancelPending || cancelRequestInFlight || quitPending) return;
    cancelPending = true;
    cancelRequestInFlight = true;
    cancelConfirmed = false;
    backendCancelRequested = Boolean(
      bootstrapSnapshot &&
      bootstrapSnapshot.status === "ready" &&
      backendSnapshot &&
      backendSnapshot.status === "starting"
    );
    cancelEl.disabled = true;
    actionStatusEl.textContent = "Requesting cancellation…";
    try {
      var cancelled = await bridge.cancelBootstrap();
      cancelRequestInFlight = false;
      if (!cancelled) {
        cancelPending = false;
        cancelConfirmed = false;
        backendCancelRequested = false;
        cancelEl.disabled = false;
        actionStatusEl.textContent = "There is no active start to cancel.";
        renderCurrent();
      } else {
        cancelConfirmed = true;
        clearConfirmedCancellationIfSettled();
        renderCurrent();
      }
    } catch (_error) {
      cancelRequestInFlight = false;
      cancelPending = false;
      cancelConfirmed = false;
      backendCancelRequested = false;
      cancelEl.disabled = false;
      fixedActionFailure("Cancellation");
      renderCurrent();
    }
  });

  quitEl.addEventListener("click", async function () {
    if (quitPending || retryPending || retryRequestInFlight || cancelRequestInFlight) return;
    quitPending = true;
    retryEl.disabled = true;
    quitEl.disabled = true;
    actionStatusEl.textContent = "Requesting a controlled quit…";
    try {
      await bridge.quitAfterBackendFailure();
    } catch (_error) {
      quitPending = false;
      quitEl.disabled = false;
      fixedActionFailure("Quit");
      renderCurrent();
    }
  });

  var unsubscribeBootstrap = bridge.onBootstrapEvent(acceptBootstrap);
  var unsubscribeBackend = bridge.onBackendEvent(function (snapshot) {
    backendEventVersion += 1;
    acceptBackend(snapshot);
  });

  function pollSnapshots() {
    if (disposed) return;
    bridge.getBootstrapSnapshot().then(acceptBootstrap).catch(function () {
      // A pushed event or the next poll remains authoritative.
    });
    var pollVersion = ++backendPollVersion;
    var eventVersion = backendEventVersion;
    bridge.getBackendState().then(function (snapshot) {
      if (pollVersion !== backendPollVersion || eventVersion !== backendEventVersion) return;
      acceptBackend(snapshot);
    }).catch(function () {
      // Keep the last stable surface; never print an unredacted bridge error.
    });
  }

  pollSnapshots();
  var pollTimer = setInterval(pollSnapshots, 700);
  var heartbeatTimer = setInterval(function () {
    if (!heartbeatActive || disposed) return;
    if (showBootstrapStallIfNeeded()) return;
    heartbeatTicks += 1;
    statusEl.textContent = heartbeatBase + " · still working · " + heartbeatTicks * 4 + "s";
  }, 4_000);

  window.addEventListener("pagehide", function () {
    if (disposed) return;
    disposed = true;
    unsubscribeBootstrap();
    unsubscribeBackend();
    clearInterval(pollTimer);
    clearInterval(heartbeatTimer);
  });
})();
