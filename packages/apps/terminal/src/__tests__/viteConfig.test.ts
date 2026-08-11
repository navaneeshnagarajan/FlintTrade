import path from "node:path";

import { describe, expect, it } from "vitest";
import { loadConfigFromFile } from "vite";

describe("Vite configuration", () => {
  it("loads through Vite's native config loader", async () => {
    const terminalRoot = path.resolve(import.meta.dirname, "../..");
    const loaded = await loadConfigFromFile(
      { command: "build", mode: "test", isSsrBuild: false, isPreview: false },
      path.join(terminalRoot, "vite.config.ts"),
      terminalRoot,
      "info",
      undefined,
      "native",
    );

    expect(loaded?.path).toBe(path.join(terminalRoot, "vite.config.ts"));
    expect(loaded?.config.resolve?.alias).toMatchObject({
      "@": path.join(terminalRoot, "src"),
    });
  });
});
