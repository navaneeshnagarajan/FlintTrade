import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";

const here = path.dirname(fileURLToPath(import.meta.url));
const outDir = process.argv[2];
if (!outDir || !path.isAbsolute(outDir)) throw new Error("Explicit companion output directory required");
await build({
  configFile: false,
  root: path.resolve(here, "../.."),
  envDir: false,
  build: {
    target: "es2022", outDir, emptyOutDir: true,
    lib: { entry: path.join(here, "schema-probe.ts"), formats: ["es"], fileName: () => "r33-schema-probe.js" },
  },
});
