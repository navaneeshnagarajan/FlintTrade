/// <reference types="vitest/config" />
import { defineConfig } from "vite";
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

export default defineConfig({
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
    alias: {
      "@": path.resolve(__dirname, "src"),
      "@flinttrade/design-system/tokens.css": path.resolve(__dirname, "../../core/design-system/src/tokens.css"),
      "@flinttrade/design-system/glass.css": path.resolve(__dirname, "../../core/design-system/src/glass.css"),
      "@flinttrade/design-system/cinematic.css": path.resolve(__dirname, "../../core/design-system/src/cinematic.css"),
      "@flinttrade/design-system": path.resolve(__dirname, "../../core/design-system/src/index.ts"),
      // Plotly widgets render through plotly.js-dist-min directly. Redirect
      // legacy Plotly specifiers so old imports do not leak the full bundle.
      "plotly.js/dist/plotly": "plotly.js-dist-min",
      "plotly.js": "plotly.js-dist-min",
    },
  },
  optimizeDeps: {
    esbuildOptions: {
      // Vite's dependency optimiser otherwise asks esbuild to downlevel modern
      // ESM dependencies to its older default browser baseline, which breaks
      // prebundling for @floating-ui and plotly.js on newer dependency graphs.
      target: "es2022",
    },
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
        manualChunks: (id: string) => {
          // React core — smallest possible initial payload
          if (
            id.includes("node_modules/react/") ||
            id.includes("node_modules/react-dom/") ||
            id.includes("node_modules/scheduler/")
          ) {
            return "vendor-react";
          }
          // React Router — route shell
          if (
            id.includes("node_modules/react-router") ||
            id.includes("node_modules/@remix-run/")
          ) {
            return "vendor-router";
          }
          // Dockview — workspace engine; large, only needed on /terminal
          if (id.includes("node_modules/dockview")) {
            return "vendor-dockview";
          }
          // Lightweight Charts — only loaded when ChartWidget mounts
          if (
            id.includes("node_modules/lightweight-charts") ||
            id.includes("node_modules/lightweight-charts-indicators") ||
            id.includes("node_modules/fancy-canvas")
          ) {
            return "vendor-lwc";
          }
          // Plotly.js — only loaded by analysis widgets (lazy)
          if (id.includes("node_modules/plotly.js")) return "vendor-plotly";
          // Glide Data Grid — canvas grid for option chain / streaming tables
          if (id.includes("node_modules/@glideapps/")) {
            return "vendor-glide";
          }
          // TanStack Query + Table — shared across many widgets
          if (id.includes("node_modules/@tanstack/")) {
            return "vendor-tanstack";
          }
          // Radix UI primitives — shared by all shadcn/ui components.
          // @floating-ui and cmdk are co-located here because they are imported
          // directly by @radix-ui packages; placing them in the same chunk
          // eliminates the vendor-radix → vendor-misc → vendor-radix circular
          // dependency that Rollup would otherwise produce.
          if (
            id.includes("node_modules/radix-ui") ||
            id.includes("node_modules/@radix-ui/") ||
            id.includes("node_modules/@floating-ui/") ||
            id.includes("node_modules/cmdk/")
          ) {
            return "vendor-radix";
          }
          // State management — Zustand + Jotai, needed immediately
          if (
            id.includes("node_modules/zustand") ||
            id.includes("node_modules/jotai")
          ) {
            return "vendor-state";
          }
          // Forms + validation — react-hook-form + zod schemas
          if (
            id.includes("node_modules/react-hook-form") ||
            id.includes("node_modules/@hookform/") ||
            id.includes("node_modules/zod")
          ) {
            return "vendor-forms";
          }
          // NOTE: lucide-react is intentionally NOT assigned a manual chunk.
          // The wildcard `import * as LucideIcons` has been removed from WidgetPicker
          // so Rollup can now tree-shake lucide per-chunk (each widget/chrome file
          // only pulls in the icons it explicitly imports).
          // Framer Motion — loaded async, not needed on initial page
          if (id.includes("node_modules/framer-motion")) return "vendor-framer";
          // d3-* plus its thin re-export/helper packages. Keeping these together
          // avoids Rollup circular chunks between vendor-d3 and vendor-misc.
          if (
            id.includes("node_modules/d3-") ||
            id.includes("node_modules/internmap/") ||
            id.includes("node_modules/victory-vendor/")
          ) return "vendor-d3";
          // Tremor wraps Recharts primitives, so keep them in one async chunk
          // instead of creating a Rollup circular chunk pair.
          // NOTE: @floating-ui is intentionally omitted here — it lives in
          // vendor-radix to avoid the circular chunk warning.
          if (
            id.includes("node_modules/recharts") ||
            id.includes("node_modules/@tremor/") ||
            id.includes("node_modules/@headlessui/") ||
            id.includes("node_modules/react-day-picker") ||
            id.includes("node_modules/react-transition-state")
          ) return "vendor-chart-ui";
          // date-fns — date formatting/parsing; pulled in by many widgets
          if (id.includes("node_modules/date-fns/")) return "vendor-dates";
          // Styling utilities — tiny but imported by every component
          if (
            id.includes("node_modules/clsx/") ||
            id.includes("node_modules/tailwind-merge/") ||
            id.includes("node_modules/class-variance-authority/")
          ) {
            return "vendor-utils";
          }
          // QR code renderer — only used by the auth/setup flows
          if (id.includes("node_modules/qrcode.react/")) return "vendor-qrcode";
          // Sentry — error monitoring, loaded lazily
          if (id.includes("node_modules/@sentry/")) return "vendor-sentry";
          // Resizable panels — layout utility, loaded with workspace
          if (id.includes("node_modules/react-resizable-panels")) return "vendor-layout";
          // Everything else in node_modules
          if (id.includes("node_modules/")) {
            return "vendor-misc";
          }
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
