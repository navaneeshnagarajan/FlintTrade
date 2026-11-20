import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const terminalSrc = join(here, "../../..");
const SMALL_TEXT = /text-\[(?:[0-9]|1[01])px\]|ft-text-overline/;

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return tsxFiles(path);
    return name.endsWith(".tsx") ? [path] : [];
  });
}

describe("Settings type scale", () => {
  it("keeps Settings, Appearance, and the theme pickers at 12px or larger", () => {
    const paths = [
      ...tsxFiles(join(terminalSrc, "tools/Settings")),
      join(terminalSrc, "components/theme/ThemePicker.tsx"),
      join(terminalSrc, "components/theme/BackgroundPicker.tsx"),
      join(terminalSrc, "routes/SettingsRoute.tsx"),
    ];
    const offenders = paths.flatMap((path) => {
      const source = readFileSync(path, "utf8");
      return SMALL_TEXT.test(source) ? [path] : [];
    });
    expect(offenders).toEqual([]);
  });
});
