/**
 * homeEntry.test.ts — FT-HOME-003
 *
 * Authed `/home` stays on the Home dashboard. Unauthenticated `/home`
 * is the password Welcome Back gate only.
 */

import { describe, expect, it, beforeEach } from "vitest";
import {
  AUTH_SESSION_STORAGE_KEY,
  CANONICAL_HOME_PATH,
  WELCOME_GATE_PATH,
  clearPersistedAuthSession,
  decideHomeEntry,
  readPersistedAuthSession,
  writePersistedAuthSession,
} from "../homeEntry";

describe("decideHomeEntry (FT-HOME-003)", () => {
  it("sends a signed-in operator to the canonical Home, not the Welcome Back gate", () => {
    expect(decideHomeEntry("logged-in")).toEqual({
      kind: "home",
      path: CANONICAL_HOME_PATH,
    });
    expect(decideHomeEntry("logged-in").kind).not.toBe("gate");
    expect(CANONICAL_HOME_PATH).toBe("/home");
  });

  it("sends an unauthenticated visitor to the Welcome Back gate only", () => {
    expect(decideHomeEntry("logged-out")).toEqual({
      kind: "gate",
      path: WELCOME_GATE_PATH,
    });
    expect(decideHomeEntry("setup-required")).toEqual({
      kind: "gate",
      path: WELCOME_GATE_PATH,
    });
    expect(WELCOME_GATE_PATH).toBe("/welcome");
  });

  it("keeps an unresolved session on the loader so /home does not flash the gate", () => {
    expect(decideHomeEntry("unknown")).toEqual({ kind: "loading" });
    expect(decideHomeEntry("transitioning")).toEqual({ kind: "loading" });
  });
});

describe("tab-scoped auth session (FT-HOME-003 refresh / address bar)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  it("round-trips a live session through sessionStorage, never localStorage", () => {
    writePersistedAuthSession({
      token: "jwt-alice",
      username: "alice",
      expiresAt: "2099-01-01T02:30:00Z",
    });

    expect(readPersistedAuthSession()).toEqual({
      token: "jwt-alice",
      username: "alice",
      expiresAt: "2099-01-01T02:30:00Z",
    });
    expect(sessionStorage.getItem(AUTH_SESSION_STORAGE_KEY)).toBeTruthy();
    expect(localStorage.getItem(AUTH_SESSION_STORAGE_KEY)).toBeNull();
  });

  it("treats a missing or expired session as unauthenticated", () => {
    expect(readPersistedAuthSession()).toBeNull();

    writePersistedAuthSession({
      token: "jwt-stale",
      username: "alice",
      expiresAt: "2020-01-01T00:00:00Z",
    });
    expect(readPersistedAuthSession()).toBeNull();
    expect(sessionStorage.getItem(AUTH_SESSION_STORAGE_KEY)).toBeNull();
  });

  it("clears the tab session so a signed-out visitor cannot skip the gate", () => {
    writePersistedAuthSession({
      token: "jwt-alice",
      username: "alice",
      expiresAt: "",
    });
    clearPersistedAuthSession();
    expect(readPersistedAuthSession()).toBeNull();
  });
});
