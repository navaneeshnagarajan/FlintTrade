import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 3001,
    proxy: {
      "/api": {
        target: process.env.VITE_OPENALGO_HOST || "http://127.0.0.1:5000",
        changeOrigin: true,
      },
      "/ws": {
        target: process.env.VITE_WS_URL || "ws://127.0.0.1:8765",
        ws: true,
      },
    },
  },
});
