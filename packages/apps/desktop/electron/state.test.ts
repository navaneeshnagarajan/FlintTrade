import { describe, expect, it, vi } from "vitest";

import { createBackendState, createBootstrapState, createUpdateState } from "./state";

describe("backend state", () => {
  it("publishes an attempt-bound starting to ready transition", () => {
    const store = createBackendState();
    const listener = vi.fn();
    store.subscribe(listener);

    const attempt = store.begin();
    expect(store.ready(attempt, 43_210)).toBe(true);
    expect(store.getSnapshot()).toEqual({
      port: 43_210,
      status: "ready",
      url: "http://127.0.0.1:43210",
    });
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("rejects stale workers after a retry begins", () => {
    const store = createBackendState();
    const first = store.begin();
    const second = store.begin();

    expect(store.ready(first, 43_210)).toBe(false);
    expect(store.ready(first, 0)).toBe(false);
    expect(store.fail(first)).toBe(false);
    expect(store.ready(second, 43_211)).toBe(true);
    expect(store.getSnapshot()).toMatchObject({ port: 43_211, status: "ready" });
  });

  it("supports post-ready failure and exact stopped publication", () => {
    const store = createBackendState();
    const failedAttempt = store.begin();
    expect(store.ready(failedAttempt, 43_210)).toBe(true);
    expect(store.fail(failedAttempt)).toBe(true);
    expect(store.getSnapshot()).toEqual({ port: null, status: "failed", url: null });
    expect(store.stopped(failedAttempt)).toBe(false);

    const drainedAttempt = store.begin();
    expect(store.ready(drainedAttempt, 43_211)).toBe(true);
    expect(store.stopped(drainedAttempt)).toBe(true);
    expect(store.getSnapshot()).toEqual({ port: null, status: "stopped", url: null });
  });

  it("validates the loopback port before publishing authority", () => {
    const store = createBackendState();
    const attempt = store.begin();

    expect(() => store.ready(attempt, 0)).toThrow(/port/i);
    expect(() => store.ready(attempt, 65_536)).toThrow(/port/i);
    expect(store.getSnapshot()).toEqual({ port: null, status: "starting", url: null });
  });
});

describe("bootstrap state", () => {
  it("publishes snapshots and returns an unsubscribe closure", () => {
    const store = createBootstrapState();
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);

    expect(store.begin("Preparing source checkout")).toBe(1);
    expect(listener).toHaveBeenLastCalledWith(
      expect.objectContaining({ attempt: 1, message: "Preparing source checkout", status: "running" }),
    );

    unsubscribe();
    store.publishForAttempt(1, { message: "Installing dependencies", progress: 25 });
    expect(listener).toHaveBeenCalledOnce();
  });

  it("isolates throwing subscribers from every terminal state transition", () => {
    const store = createBootstrapState();
    const observer = vi.fn();
    store.subscribe(() => {
      throw new Error("renderer broadcast failed");
    });
    store.subscribe(observer);

    const completedAttempt = store.begin("Preparing source checkout");
    expect(store.complete(completedAttempt)).toBe(true);
    expect(store.getSnapshot()).toMatchObject({ phase: "complete", status: "ready" });

    const failedStore = createBootstrapState();
    const failedObserver = vi.fn();
    failedStore.subscribe(() => {
      throw new Error("renderer broadcast failed");
    });
    failedStore.subscribe(failedObserver);
    const failedAttempt = failedStore.begin("Preparing source checkout");
    expect(failedStore.fail(failedAttempt, "Bootstrap failed")).toBe(true);
    expect(failedStore.getSnapshot()).toMatchObject({ phase: "failed", status: "failed" });

    expect(observer).toHaveBeenCalledTimes(2);
    expect(failedObserver).toHaveBeenCalledTimes(2);
  });

  it("allows retry only from failure and rejects stale attempt updates", () => {
    const store = createBootstrapState();
    expect(store.retry()).toBe(false);
    const firstAttempt = store.begin("Starting");
    expect(store.retry()).toBe(false);
    expect(store.fail(firstAttempt, "A redacted failure occurred")).toBe(true);
    expect(store.retry()).toBe(true);
    expect(store.getSnapshot().attempt).toBe(2);
    expect(store.publishForAttempt(firstAttempt, { message: "stale worker" })).toBe(false);
    expect(store.getSnapshot().message).not.toBe("stale worker");
  });

  it("turns cancellation into a recoverable failure", () => {
    const store = createBootstrapState();
    const attempt = store.begin("Cloning source");
    expect(store.cancel(attempt)).toBe(true);
    expect(store.getSnapshot()).toMatchObject({ phase: "cancelled", status: "failed" });

    const cancelled = store.getSnapshot();
    expect(store.publishForAttempt(attempt, { message: "worker kept running", progress: 80 })).toBe(false);
    expect(store.complete(attempt, "worker reported ready")).toBe(false);
    expect(store.fail(attempt, "worker reported another failure")).toBe(false);
    expect(store.getSnapshot()).toBe(cancelled);

    expect(store.retry()).toBe(true);
  });

  it("keeps an earlier failure terminal for the same attempt", () => {
    const store = createBootstrapState();
    const attempt = store.begin("Installing tools");
    expect(store.fail(attempt, "Installation failed")).toBe(true);

    const failed = store.getSnapshot();
    expect(store.publishForAttempt(attempt, { message: "late progress", progress: 90 })).toBe(false);
    expect(store.complete(attempt)).toBe(false);
    expect(store.fail(attempt, "late failure")).toBe(false);
    expect(store.cancel(attempt)).toBe(false);
    expect(store.getSnapshot()).toBe(failed);
  });

  it("allows only containment-style fail-closed state to override same-attempt cancellation", () => {
    const store = createBootstrapState();
    const attempt = store.begin("Running command");
    expect(store.cancel(attempt)).toBe(true);

    expect(store.failClosed(attempt, "Process containment could not be proven.")).toBe(true);
    expect(store.getSnapshot()).toMatchObject({
      failure: "Process containment could not be proven.",
      message: "Process containment could not be proven.",
      phase: "failed",
      status: "failed",
    });
    expect(store.failClosed(attempt - 1, "stale")).toBe(false);
  });
});

describe("update state", () => {
  it("keeps source and shell update state explicitly distinct", () => {
    const source = createUpdateState("source");
    const shell = createUpdateState("shell");

    const attempt = source.begin("checking", "Checking source updates");
    expect(source.available(attempt, "main@abc123")).toBe(true);

    expect(source.getSnapshot()).toMatchObject({
      attempt: 1,
      kind: "source",
      status: "available",
      version: "main@abc123",
    });
    expect(shell.getSnapshot()).toMatchObject({ attempt: 0, kind: "shell", status: "idle", version: null });
  });

  it("rejects stale workers after a newer update attempt begins", () => {
    const store = createUpdateState("source");
    const firstAttempt = store.begin("checking", "Checking source updates");
    expect(store.publishForAttempt(firstAttempt, { message: "Resolving revision", progress: 20 })).toBe(true);

    const secondAttempt = store.begin("applying", "Applying source update", "main@def456");
    expect(secondAttempt).toBe(2);
    expect(store.available(firstAttempt, "main@abc123")).toBe(false);
    expect(store.fail(firstAttempt, "stale failure")).toBe(false);
    expect(store.getSnapshot()).toMatchObject({
      attempt: secondAttempt,
      message: "Applying source update",
      status: "applying",
      version: "main@def456",
    });
  });

  it("keeps terminal update states immutable for the same attempt", () => {
    const store = createUpdateState("source");
    const attempt = store.begin("applying", "Applying source update", "main@abc123");

    expect(store.complete(attempt, "Source update installed")).toBe(true);
    const completed = store.getSnapshot();
    expect(completed).toMatchObject({ progress: 100, status: "complete", version: "main@abc123" });
    expect(store.publishForAttempt(attempt, { message: "late progress", progress: 90 })).toBe(false);
    expect(store.fail(attempt, "late failure")).toBe(false);
    expect(store.getSnapshot()).toBe(completed);
  });

  it("publishes attempt-bound unavailable and failure results", () => {
    const unavailableStore = createUpdateState("shell");
    const unavailableAttempt = unavailableStore.begin("checking", "Checking Electron shell updates");
    expect(unavailableStore.unavailable(unavailableAttempt, "No shell update is available")).toBe(true);
    expect(unavailableStore.getSnapshot()).toMatchObject({
      failure: null,
      message: "No shell update is available",
      progress: null,
      status: "unavailable",
      version: null,
    });

    const failedStore = createUpdateState("source");
    const failedAttempt = failedStore.begin("checking", "Checking source updates");
    expect(failedStore.fail(failedAttempt, "Source provenance could not be verified")).toBe(true);
    expect(failedStore.getSnapshot()).toMatchObject({
      failure: "Source provenance could not be verified",
      message: "Source provenance could not be verified",
      status: "failed",
    });
  });
});
