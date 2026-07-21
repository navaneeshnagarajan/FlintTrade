import { describe, expect, it, vi } from "vitest";

import { createBootstrapState, createUpdateState } from "./state";

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
});

describe("update state", () => {
  it("keeps source and shell update state explicitly distinct", () => {
    const source = createUpdateState("source");
    const shell = createUpdateState("shell");

    source.publish({ status: "available", version: "main@abc123" });

    expect(source.getSnapshot()).toMatchObject({ kind: "source", status: "available", version: "main@abc123" });
    expect(shell.getSnapshot()).toMatchObject({ kind: "shell", status: "idle", version: null });
  });
});
