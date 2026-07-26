/**
 * Live-write-path coverage guard.
 *
 * Every client function that can arm or dispatch a live order must either
 * (a) fail closed on an unready native write target via
 * `assertNativeWriteTargetReadyOrThrow`, or (b) carry a written exemption
 * saying why gating it would be unsafe (risk-reducing cancels must never be
 * blocked by hydration state).
 *
 * This guard exists because three write paths — the Ditto mirror arming, the
 * Action Centre approval, and the smart-route cancel — reached the broker
 * with no assert and nothing in either the service tests or the widget tests
 * would have failed. The per-function unit tests check behaviour; this one
 * checks that no NEW write path can be added without making that choice
 * explicitly.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const servicesDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function readService(file: string): string {
  return readFileSync(resolve(servicesDir, file), "utf8");
}

/**
 * Write paths that MUST call the assert. Each entry names the exported
 * function and the file it lives in.
 */
const GATED_WRITE_PATHS: ReadonlyArray<{ file: string; fn: string; why: string }> = [
  {
    file: "ftApi.ditto.ts",
    fn: "startDittoMirror",
    why: "arms a live multi-account order path",
  },
  {
    file: "ftApi.ditto.ts",
    fn: "setDittoAccountEnabled",
    why: "widens the live mirror's blast radius when enabling",
  },
  {
    file: "ftApi.trading.ts",
    fn: "approveOrder",
    why: "releases a queued order to the broker",
  },
  {
    file: "ftApi.trading.ts",
    fn: "startSmartRoute",
    why: "starts a job that slices real orders into the market",
  },
];

/**
 * Write paths deliberately NOT gated. Each must carry a written rationale in
 * its docstring — an ungated write path with no explanation is the exact
 * state this guard exists to prevent.
 */
const EXEMPT_WRITE_PATHS: ReadonlyArray<{ file: string; fn: string; marker: RegExp }> = [
  {
    file: "ftApi.trading.ts",
    fn: "cancelSmartRoute",
    marker: /NOT write-target gated/i,
  },
  {
    file: "ftApi.trading.ts",
    fn: "cancelBracket",
    marker: /NEVER fails closed on an unresolved native account/i,
  },
  {
    file: "ftApi.trading.ts",
    fn: "rejectOrder",
    marker: /Not gated/i,
  },
  {
    file: "ftApi.ditto.ts",
    fn: "stopDittoMirror",
    marker: /NOT write-target gated/i,
  },
];

/** Extract the source of a single exported function/const, docstring included. */
function extractDeclaration(source: string, fn: string): string {
  const idx = source.indexOf(`export const ${fn}`) >= 0
    ? source.indexOf(`export const ${fn}`)
    : source.indexOf(`export async function ${fn}`) >= 0
      ? source.indexOf(`export async function ${fn}`)
      : source.indexOf(`export function ${fn}`);
  expect(idx, `${fn} not found in source`).toBeGreaterThanOrEqual(0);
  // Include the preceding docstring block.
  const docStart = source.lastIndexOf("/**", idx);
  const start = docStart >= 0 && idx - docStart < 1200 ? docStart : idx;
  // Read to the next top-level export, which bounds the declaration.
  const nextExport = source.indexOf("\nexport ", idx + 10);
  const end = nextExport > 0 ? nextExport : source.length;
  return source.slice(start, end);
}

describe("live write paths fail closed on an unready native target", () => {
  for (const { file, fn, why } of GATED_WRITE_PATHS) {
    it(`${fn} asserts the write target — it ${why}`, () => {
      const decl = extractDeclaration(readService(file), fn);
      const asserts =
        /assertNativeWriteTargetReadyOrThrow/.test(decl) ||
        // Ditto routes both arming calls through one shared helper.
        /assertMirrorArmingAllowed/.test(decl) ||
        // Smart route resolves its target through a wrapper that asserts.
        /withSmartRouteBrokerTarget/.test(decl);
      expect(
        asserts,
        `${fn} dispatches or arms a live order path but never reaches the native write-target assert`,
      ).toBe(true);
    });
  }
});

describe("ungated write paths carry a written rationale", () => {
  for (const { file, fn, marker } of EXEMPT_WRITE_PATHS) {
    it(`${fn} documents why it is not gated`, () => {
      const decl = extractDeclaration(readService(file), fn);
      expect(
        marker.test(decl),
        `${fn} is an ungated write path with no written rationale — either gate it or say why gating it would be unsafe`,
      ).toBe(true);
    });
  }
});

describe("the shared ditto arming helper reaches the real assert", () => {
  it("assertMirrorArmingAllowed calls assertNativeWriteTargetReadyOrThrow", () => {
    const source = readService("ftApi.ditto.ts");
    const helper = source.slice(
      source.indexOf("function assertMirrorArmingAllowed"),
      source.indexOf("export const getDittoAccounts"),
    );
    expect(helper).toContain("assertNativeWriteTargetReadyOrThrow");
  });
});
