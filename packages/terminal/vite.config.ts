/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  optimizeDeps: {
    exclude: ["react-plotly.js"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
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
    chunkSizeWarningLimit: 300,
    target: "es2022",
    rollupOptions: {
      // Glide Data Grid v6 has optional peer deps we don't use. Externalize them
      // to suppress "unresolved import" build errors without installing them.
      //   react-responsive-carousel — image overlay editor (unused)
      //   marked — markdown cell renderer (unused)
      external: ["react-responsive-carousel", "marked"],
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
          // d3-* — heavy math/scale/shape modules, lazy-loaded via Tremor/Recharts
          if (id.includes("node_modules/d3-")) return "vendor-d3";
          // Recharts — chart rendering (lazy, only dashboards/lab/invest)
          if (id.includes("node_modules/recharts")) return "vendor-recharts";
          // Tremor + headlessui — dashboard UI components (lazy)
          // NOTE: @floating-ui is intentionally omitted here — it lives in
          // vendor-radix to avoid the circular chunk warning.
          if (
            id.includes("node_modules/@tremor/") ||
            id.includes("node_modules/@headlessui/") ||
            id.includes("node_modules/react-day-picker") ||
            id.includes("node_modules/react-transition-state")
          ) return "vendor-tremor";
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
  },
});
