/// <reference types="vitest" />
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  // GitHub Pages serves the demo under /<repo>/ — set VITE_BASE=/biopilot/ for that build.
  base: process.env.VITE_BASE ?? "/",
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    // BIOPILOT_API_PROXY lets the E2E suite point each dev server at its own backend.
    proxy: {
      "/api": { target: process.env.BIOPILOT_API_PROXY ?? "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  test: { environment: "jsdom", globals: false, include: ["src/**/*.test.{ts,tsx}"] },
});
