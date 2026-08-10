// defineConfig comes from vitest/config (not vite) so the `test` block
// typechecks: the vitest module augmentation lands on vitest's own vite 7
// module identity, not the vite 6 copy this package resolves.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { visualizer } from "rollup-plugin-visualizer";
import fs from "fs";
import path from "path";

function readFlintTradeVersion(): string {
  const repoRoot = path.resolve(__dirname, "../../..");
  const versionPath = path.join(repoRoot, "VERSION");
  try {
    const value = fs.readFileSync(versionPath, "utf8").trim();
    return value.startsWith("v") ? value : `v${value}`;
  } catch {
    return `v${process.env.npm_package_version || "0.0.0-dev"}`;
  }
}

const flintTradeVersion = readFlintTradeVersion();
const publicDemoBuild = process.env.FLINTTRADE_PUBLIC_DEMO_BUILD === "1";

export default defineConfig({
  // The site demo is public output. Disabling dotenv loading in that build is
  // fail-closed: neither .env.production nor any other terminal .env* file can
  // populate import.meta.env. The launcher also strips inherited VITE_* values.
  envDir: publicDemoBuild ? false : undefined,
  define: {
    "import.meta.env.VITE_FLINTTRADE_VERSION": JSON.stringify(flintTradeVersion),
  },
  plugins: [
    react(),
    tailwindcss(),
    ...(process.env.ANALYZE
      ? [
          visualizer({
            filename: "dist/bundle-stats.html",
            open: false,
            gzipSize: true,
            brotliSize: true,
          }),
        ]
      : []),
  ],
  resolve: {
    // The design-system is consumed as a file: link and declares react as a
    // peer dependency. Vite 8's Rolldown/oxc resolver does not fall back to
    // the consuming project's node_modules for bare imports inside linked
    // packages the way Vite 7's resolver did, so dedupe react explicitly —
    // this also guarantees a single React copy in the bundle.
    dedupe: ["react", "react-dom"],
    alias: {
      "@": path.resolve(__dirname, "src"),
      "@flinttrade/design-system/tokens.css": path.resolve(__dirname, "../../core/design-system/src/tokens.css"),
      "@flinttrade/design-system/glass.css": path.resolve(__dirname, "../../core/design-system/src/glass.css"),
      "@flinttrade/design-system/cinematic.css": path.resolve(__dirname, "../../core/design-system/src/cinematic.css"),
      "@flinttrade/design-system/brand": path.resolve(__dirname, "../../core/design-system/src/brand/index.ts"),
      "@flinttrade/design-system": path.resolve(__dirname, "../../core/design-system/src/index.ts"),
      // Plotly widgets render through plotly.js-dist-min directly. Redirect
      // legacy Plotly specifiers so old imports do not leak the full bundle.
      "plotly.js/dist/plotly": "plotly.js-dist-min",
      "plotly.js": "plotly.js-dist-min",
    },
  },
  optimizeDeps: {
    rolldownOptions: {
      // Vite 8's dependency optimiser runs on Rolldown (esbuildOptions is
      // deprecated and ignored). Keep the modern target explicit so the
      // optimiser never downlevels modern ESM dependencies below the app's
      // build target, which previously broke prebundling for @floating-ui
      // and plotly.js on newer dependency graphs.
      transform: { target: "es2022" },
    },
    // Perspective ships WASM + workers resolved via import.meta.url;
    // esbuild prebundling breaks those relative asset URLs, so the three
    // packages must reach the browser unbundled in dev.
    exclude: [
      "@finos/perspective",
      "@finos/perspective-viewer",
      "@finos/perspective-viewer-datagrid",
    ],
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      // FlintTrade backend (port 5100) — must be listed before /api
      // Port 5100 avoids conflict with OpenAlgo multi-instance (5000-5009)
      "/ft-api": {
        target: process.env.VITE_FLINTTRADE_HOST || "http://127.0.0.1:5100",
        changeOrigin: true,
        rewrite: (p: string) => p.replace(/^\/ft-api/, ""),
      },
      // OpenAlgo REST API (port 5000)
      "/api": {
        target: process.env.VITE_OPENALGO_HOST || "http://127.0.0.1:5000",
        changeOrigin: true,
      },
      "/ws": {
        target: process.env.VITE_OPENALGO_WS || "ws://127.0.0.1:8765",
        ws: true,
        rewrite: (p: string) => p.replace(/^\/ws/, ""),
      },
    },
  },
  build: {
    // Plotly powers 3D volatility surfaces and is isolated in a lazy analysis
    // chunk. Keep the warning budget above that known async payload so new
    // warnings point at unexpected growth, not the intentional chart engine.
    chunkSizeWarningLimit: 5_000,
    target: "es2022",
    rollupOptions: {
      onwarn(warning, warn) {
        if (
          warning.code === "INVALID_ANNOTATION" &&
          typeof warning.id === "string" &&
          warning.id.includes("@glideapps/glide-data-grid")
        ) {
          return;
        }
        warn(warning);
      },
      // NOTE: do NOT externalise @glideapps/glide-data-grid's optional peer deps
      // (react-responsive-carousel — image overlay editor; marked — markdown cell
      // renderer). They are statically imported by glide-data-grid's module graph,
      // so externalising them leaves a bare `import "react-responsive-carousel"` in
      // the bundle that the browser cannot resolve at runtime — crashing every grid
      // widget that loads that path (e.g. the Option Chain). Both are installed
      // (devDependencies), so Vite bundles them cleanly. See the campaign log.
      external: [],
      output: {
        // Vite 8 bundles with Rolldown, whose native chunking control is
        // `codeSplitting` — the function-form `manualChunks` compat shim
        // silently merged the vendor-react group into vendor-flexlayout, so
        // the groups below are the direct migration of the old if-chain
        // (first matching group wins, mirroring the original ordering).
        codeSplitting: {
          groups: [
            // React core — smallest possible initial payload
            {
              name: "vendor-react",
              test: /node_modules[\\/](?:react|react-dom|scheduler)[\\/]/,
            },
            // React Router — route shell
            {
              name: "vendor-router",
              test: /node_modules[\\/](?:react-router|@remix-run\/)/,
            },
            // FlexLayout — workspace engine; large, only needed on /terminal
            { name: "vendor-flexlayout", test: /node_modules[\\/]flexlayout-react/ },
            // Perspective — WASM analytics engine; only loaded by the
            // Portfolio Pivot widget (lazy)
            { name: "vendor-perspective", test: /node_modules[\\/]@finos\/perspective/ },
            // Lightweight Charts — only loaded when ChartWidget mounts
            {
              name: "vendor-lwc",
              test: /node_modules[\\/](?:lightweight-charts|fancy-canvas)/,
            },
            // Plotly.js — only loaded by analysis widgets (lazy)
            { name: "vendor-plotly", test: /node_modules[\\/]plotly\.js/ },
            // Glide Data Grid — canvas grid for option chain / streaming tables
            { name: "vendor-glide", test: /node_modules[\\/]@glideapps\// },
            // TanStack Query + Table — shared across many widgets
            { name: "vendor-tanstack", test: /node_modules[\\/]@tanstack\// },
            // Radix UI primitives — shared by all shadcn/ui components.
            // @floating-ui and cmdk are co-located here because they are imported
            // directly by @radix-ui packages; placing them in the same chunk
            // eliminates the vendor-radix → vendor-misc → vendor-radix circular
            // dependency that the bundler would otherwise produce.
            {
              name: "vendor-radix",
              test: /node_modules[\\/](?:radix-ui|@radix-ui\/|@floating-ui\/|cmdk\/)/,
            },
            // State management — Zustand + Jotai, needed immediately
            { name: "vendor-state", test: /node_modules[\\/](?:zustand|jotai)/ },
            // Forms + validation — react-hook-form + zod schemas
            {
              name: "vendor-forms",
              test: /node_modules[\\/](?:react-hook-form|@hookform\/|zod)/,
            },
            // NOTE: lucide-react is intentionally NOT assigned a chunk group.
            // The wildcard `import * as LucideIcons` has been removed from WidgetPicker
            // so the bundler can now tree-shake lucide per-chunk (each widget/chrome
            // file only pulls in the icons it explicitly imports).
            // Framer Motion — loaded async, not needed on initial page
            { name: "vendor-framer", test: /node_modules[\\/]framer-motion/ },
            // d3-* plus its thin re-export/helper packages. Keeping these together
            // avoids circular chunks between vendor-d3 and vendor-misc.
            {
              name: "vendor-d3",
              test: /node_modules[\\/](?:d3-|internmap\/|victory-vendor\/)/,
            },
            // Tremor wraps Recharts primitives, so keep them in one async chunk
            // instead of creating a circular chunk pair.
            // NOTE: @floating-ui is intentionally omitted here — it lives in
            // vendor-radix to avoid the circular chunk warning.
            {
              name: "vendor-chart-ui",
              test: /node_modules[\\/](?:@tremor\/|@headlessui\/|react-day-picker|react-transition-state)/,
            },
            // date-fns — date formatting/parsing; pulled in by many widgets
            { name: "vendor-dates", test: /node_modules[\\/]date-fns\// },
            // Styling utilities — tiny but imported by every component
            {
              name: "vendor-utils",
              test: /node_modules[\\/](?:clsx|tailwind-merge|class-variance-authority)\//,
            },
            // QR code renderer — only used by the auth/setup flows
            { name: "vendor-qrcode", test: /node_modules[\\/]qrcode\.react\// },
            // Sentry — error monitoring, loaded lazily
            { name: "vendor-sentry", test: /node_modules[\\/]@sentry\// },
            // Resizable panels — layout utility, loaded with workspace
            { name: "vendor-layout", test: /node_modules[\\/]react-resizable-panels/ },
            // Everything else in node_modules
            { name: "vendor-misc", test: /node_modules[\\/]/ },
          ],
        },
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    silent: "passed-only",
    // Vitest's worker pool blows the heap when `pool: 'threads'` because
    // every thread shares a single process and each jsdom worker holds a
    // full DOM + the entire app's module graph in memory. With ~260 test
    // files and 4 concurrent workers, that's ~4 × 2 GB of resident memory,
    // which OOMs both the 16 GB dev box and the 7 GB CI Ubuntu runner.
    // `node-widget-tests-1` and `node-widget-tests-3` reliably died here.
    //
    // Switching to `pool: 'forks'` (Vitest's default, but we used to
    // override) puts each test file in its own child process, so the
    // OS reclaims the heap when the file finishes. Context7 confirms
    // this is the canonical fix for jsdom + ESM heap exhaustion (see
    // https://vitest.dev/guide/common-errors#segfaults-and-native-code-errors
    // and https://vitest.dev/guide/improving-performance#pool).
    pool: "forks",
    // Keep the default conservative for jsdom-heavy suites on CI and newer
    // Node runtimes; override locally with VITEST_MAX_WORKERS. The
    // VITEST_MAX_FORKS fallback keeps old local scripts working.
    maxWorkers: Number(process.env.VITEST_MAX_WORKERS ?? process.env.VITEST_MAX_FORKS ?? 1),
    isolate: true,
    // Per-test wall-clock cap. Most tests finish in <100 ms; 10 s catches
    // hangs (e.g. a stub fetch that never resolves) before the whole suite
    // times out.
    testTimeout: 10_000,
    hookTimeout: 10_000,
  },
});
