import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["electron/**/*.test.ts"],
    passWithNoTests: false,
    // The bootstrap and source-update suites are integration-grade: they
    // spawn real processes, build real tool trees and archives, and probe
    // executables. Vitest's 5s default intermittently kills them on loaded
    // 2-core CI runners — observed as four different bootstrap tests
    // failing across four consecutive CI runs (three as truncated fixture
    // output masquerading as "unexpected version", one as an explicit
    // 5000ms timeout) while local and single-file CI runs stay green.
    // 30s changes no assertion — it only stops penalising slow hardware.
    testTimeout: 30_000,
    hookTimeout: 30_000,
  },
});
