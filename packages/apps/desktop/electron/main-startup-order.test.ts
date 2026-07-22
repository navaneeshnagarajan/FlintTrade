import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const source = readFileSync(new URL("./main.ts", import.meta.url), "utf8");

describe("desktop main-process entrypoint", () => {
  it("wins the singleton lock before protocol, userData, or bootstrap path setup", () => {
    const lock = source.indexOf("const hasSingleInstanceLock = app.requestSingleInstanceLock();");
    expect(lock).toBeGreaterThanOrEqual(0);

    for (const mutation of [
      "protocol.registerSchemesAsPrivileged(",
      'app.getPath("appData")',
      'app.setPath("userData", shellUserData)',
      "resolveDesktopPaths({",
      "app.getAppPath()",
    ]) {
      expect(source.indexOf(mutation), mutation).toBeGreaterThan(lock);
    }
  });

  it("only quits when the singleton lock is lost", () => {
    const losingBranch = source.match(
      /if \(!hasSingleInstanceLock\) \{\s*([\s\S]*?)\s*\} else \{/,
    );

    expect(losingBranch?.[1]?.trim()).toBe("app.quit();");
  });
});
