/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      // FlintTrade backend (port 5001) — must be listed before /api
      "/ft-api": {
        target: process.env.VITE_FLINTTRADE_HOST || "http://127.0.0.1:5001",
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
    rollupOptions: {
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
          // Glide Data Grid — canvas grid for option chain / streaming tables
          if (id.includes("node_modules/@glideapps/")) {
            return "vendor-glide";
          }
          // TanStack Query + Table — shared across many widgets
          if (id.includes("node_modules/@tanstack/")) {
            return "vendor-tanstack";
          }
          // Radix UI primitives — shared by all shadcn/ui components
          if (
            id.includes("node_modules/radix-ui") ||
            id.includes("node_modules/@radix-ui/")
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
          // Everything else in node_modules EXCEPT lucide-react.
          // lucide-react must NOT be assigned a manual chunk: Rollup tree-shakes
          // it per-widget chunk (each widget only pulls in its own icons).
          // Forcing it into one chunk would bundle all ~1000 icons together (896 KB).
          if (
            id.includes("node_modules/") &&
            !id.includes("node_modules/lucide-react")
          ) {
            return "vendor-misc";
          }
        },
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: [],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
