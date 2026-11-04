import { describe, expect, it, vi } from "vitest";
import { z } from "zod";
import {
  decodeConnectResult, decodeManagedAccountResult, decodeReloginResult, NativeCredentialsRequired,
} from "../nativeAccountResult";

const target = { broker: "dhan", accountId: "Synthetic" };
const key = "synthetic-operation";
function receipt() {
  return { operationId: key, kind: "reconnect", state: "committed", reason: null, credentialGeneration: 1 };
}
function ordinary() { return { receipt: receipt(), runtimeStatus: "session_present" }; }
function recovered() {
  return { receipt: receipt(), runtimeStatus: "read_only_recovery", recovery: {
    ...target, readOnly: true, writeAuthority: "none", grantAuthority: "none", reconciliationRequired: true,
    census: { complete: true, revision: "a".repeat(64), runIds: ["synthetic-run"] },
  } };
}
const decode = (value: unknown) => decodeManagedAccountResult(value, key, "reconnect", target);
const unavailable = /outcome unavailable.*authentication may have occurred/i;

describe("strict account-result contract (synthetic, no trading authority)", () => {
  const statuses = ["session_present", "session_unavailable", "cleanup_pending", "blocked", "read_only_recovery"];
  const allowed: Record<string, string[]> = {
    committed: ["session_present", "session_unavailable", "cleanup_pending", "read_only_recovery"],
    rejected: ["session_unavailable", "cleanup_pending"],
    authentication_unknown: ["blocked"], blocked: ["blocked"],
  };
  for (const state of Object.keys(allowed)) for (const runtimeStatus of statuses) {
    it(`retains the ${state}/${runtimeStatus} cross-field rule`, () => {
      const value = runtimeStatus === "read_only_recovery" ? recovered() : ordinary();
      value.runtimeStatus = runtimeStatus;
      value.receipt.state = state;
      Object.assign(value.receipt, { credentialGeneration: state === "committed" ? 1 : null });
      if (allowed[state].includes(runtimeStatus)) expect(decode(value)).toBe(value);
      else expect(() => decode(value)).toThrow(unavailable);
    });
  }
  const objects = [
    { label: "ordinary", make: ordinary, path: [] },
    { label: "receipt", make: ordinary, path: ["receipt"] },
    { label: "recovery", make: recovered, path: ["recovery"] },
    { label: "census", make: recovered, path: ["recovery", "census"] },
  ];
  for (const { label, make, path } of objects) {
    const at = (value: unknown) => path.reduce((node, part) => node[part] as Record<string, unknown>, value as Record<string, unknown>);
    for (const field of Object.keys(at(make()))) {
      it(`requires own ${label}.${field}`, () => {
        const value = make(); const node = at(value); const old = node[field];
        delete node[field];
        expect(() => decode(value)).toThrow(unavailable);
        Object.setPrototypeOf(node, { [field]: old });
        expect(() => decode(value)).toThrow(unavailable);
      });
    }
    it.each(["unexpected", "constructor", "toString", "__proto__"])(`refuses unknown ${label} key %s`, field => {
      const value = make(); Object.defineProperty(at(value), field, { value: true, enumerable: true });
      expect(() => decode(value)).toThrow(unavailable);
      expect(decode(make())).toEqual(make());
    });
  }
  for (const generation of [0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1, NaN, Infinity, -Infinity, "1", true, null, undefined]) {
    it(`refuses invalid committed generation ${String(generation)}`, () => {
      const value = ordinary(); Object.assign(value.receipt, { credentialGeneration: generation });
      expect(() => decode(value)).toThrow(unavailable);
    });
  }
  it("retains safe generation bounds and exact opaque strings", () => {
    const value = recovered(); value.receipt.credentialGeneration = Number.MAX_SAFE_INTEGER;
    value.receipt.operationId = " key "; value.recovery.accountId = " Synthetic ";
    value.recovery.census.runIds = [" run ", "RUN"];
    expect(decodeManagedAccountResult(value, " key ", "reconnect", { ...target, accountId: " Synthetic " })).toBe(value);
    expect(() => decodeManagedAccountResult(value, "key", "reconnect", target)).toThrow(unavailable);
  });
  it.each(["operationId", "kind"])("binds exact receipt %s", field => {
    const value = ordinary(); Object.assign(value.receipt, { [field]: field === "kind" ? "connect" : "other" });
    expect(() => decode(value)).toThrow(unavailable);
  });
  it.each(["broker", "accountId"])("binds exact recovery %s", field => {
    const value = recovered(); Object.assign(value.recovery, { [field]: "foreign" });
    expect(() => decode(value)).toThrow(unavailable);
  });
  it("requires a submitted recovery target without manufacturing one", () => {
    expect(() => decodeManagedAccountResult(recovered(), key, "reconnect")).toThrow(unavailable);
    expect(decodeManagedAccountResult(ordinary(), key, "reconnect")).toEqual(ordinary());
  });
  it.each(["readOnly", "writeAuthority", "grantAuthority", "reconciliationRequired"])("retains restriction %s", field => {
    const value = recovered(); Object.assign(value.recovery, { [field]: null });
    expect(() => decode(value)).toThrow(unavailable);
  });
  it.each([[], [""], ["same", "same"], [1], [null], [undefined], "synthetic-run"].map(runIds => [runIds]))("refuses malformed run IDs %j", runIds => {
    const value = recovered(); Object.assign(value.recovery.census, { runIds });
    expect(() => decode(value)).toThrow(unavailable);
  });
  it("preserves non-JSON sparse-array compatibility without accepting explicit undefined", () => {
    const value = recovered(); value.recovery.census.runIds = new Array<string>(1);
    expect(decode(value)).toBe(value);
    Object.assign(value.recovery.census, { runIds: [undefined] });
    expect(() => decode(value)).toThrow(unavailable);
  });
  it("retains valid run IDs without consulting an own array constructor", () => {
    const value = recovered();
    Object.defineProperty(value.recovery.census.runIds, "constructor", { value: true, enumerable: true });
    expect(decode(value)).toBe(value);
    expect(value.recovery.census.runIds[0]).toBe("synthetic-run");
  });
  it.each(["A".repeat(64), "a".repeat(63), " a".repeat(32), ""])("refuses malformed census revision %j", revision => {
    const value = recovered(); value.recovery.census.revision = revision;
    expect(() => decode(value)).toThrow(unavailable);
  });
  it.each([undefined, null, recovered().recovery])("refuses any own recovery field on an ordinary receipt", recovery => {
    const value = ordinary(); Object.defineProperty(value, "recovery", { value: recovery });
    expect(() => decode(value)).toThrow(unavailable);
  });
  it("retains own nonenumerable required fields and ignores inherited unknown fields", () => {
    const value = ordinary(); Object.defineProperty(value.receipt, "reason", { value: null, enumerable: false });
    Object.setPrototypeOf(value.receipt, { inheritedUnknown: true });
    expect(decode(value)).toBe(value);
  });
});

describe("legacy result separation and app-owned errors", () => {
  it.each([true, false])("preserves legacy connect connected=%s", connected => {
    expect(decodeConnectResult({ connected, login: "" }, key)).toEqual({ connected, login: "" });
  });
  it("refuses mixed legacy/native and Paper envelopes", () => {
    for (const value of [{ ...ordinary(), connected: true, login: "" }, { connected: true }, { mode: "paper", session: { has_session: true } }]) {
      expect(() => decodeConnectResult(value, key)).toThrow(unavailable);
      expect(() => decodeReloginResult(value, key)).toThrow(unavailable);
    }
  });
  it.each([undefined, null, 0, -1, 0.5, Number.MAX_VALUE])("preserves finite/optional legacy expiry %s", expires_at => {
    const value = { session: { has_session: true, expires_at, read_only: false, login: "" }, login: "" };
    expect(decodeReloginResult(value, key)).toBe(value.session);
  });
  it.each([NaN, Infinity, -Infinity, "0", false])("refuses malformed legacy expiry %s", expires_at => {
    expect(() => decodeReloginResult({ session: { has_session: true, expires_at } }, key)).toThrow(unavailable);
  });
  it("only valid legacy rejection owns the fresh-credentials error", () => {
    expect(() => decodeReloginResult({ session: { has_session: false } }, key)).toThrow(NativeCredentialsRequired);
    for (const value of [{ session: { has_session: false, extra: true } }, { session: { has_session: false, expires_at: Infinity } }]) {
      expect(() => decodeReloginResult(value, key)).toThrow(unavailable);
      expect(() => decodeReloginResult(value, key)).not.toThrow(NativeCredentialsRequired);
    }
  });
  it("validates inherited optional legacy leaves without treating them as required", () => {
    const session = Object.assign(Object.create({ expires_at: Infinity }), { has_session: true });
    expect(() => decodeReloginResult({ session }, key)).toThrow(unavailable);
    Object.setPrototypeOf(session, { expires_at: 0 });
    expect(decodeReloginResult({ session }, key)).toBe(session);
  });
  it("constructs and decodes cold under no-eval CSP", async () => {
    z.config({ jitless: false }); vi.resetModules();
    const forbidden = vi.fn(() => { throw new Error("dynamic compilation forbidden"); });
    vi.stubGlobal("Function", forbidden);
    try {
      const cold = await import("../nativeAccountResult");
      expect(cold.decodeConnectResult({ connected: true, login: "" }, key)).toEqual({ connected: true, login: "" });
      expect(forbidden).not.toHaveBeenCalled();
    } finally { vi.unstubAllGlobals(); }
  });
});
