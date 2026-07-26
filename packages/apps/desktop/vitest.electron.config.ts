import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["electron/**/*.test.ts"],
    passWithNoTests: false,
    // Run one file at a time.
    //
    // These are process-supervision tests: they spawn real process trees and
    // assert on WALL-CLOCK behaviour — a descendant must die before its 600 ms
    // timer, a lease must be reclaimed, a containment sweep must out-run an
    // escapee. Vitest's default parallelism puts ~50 other files on the same
    // two CI cores, and under that load the deadlines these tests measure are
    // no longer the deadlines the code was designed against.
    //
    // The evidence: the failure count moved with UNRELATED changes. Adding a
    // diagnostic probe took it 3 → 18; giving a slow PowerShell test a longer
    // timeout (so it ran 8 s instead of being killed at 5 s) did the same,
    // while `bootstrap-io.ts` stayed byte-identical throughout. That is
    // contention, not a containment defect.
    //
    // Sequential execution costs wall-clock in CI and buys a signal that means
    // something. A timing test that shares a core is not measuring the code.
    fileParallelism: false,
  },
});
