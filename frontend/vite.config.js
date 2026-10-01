import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Aplikasi mandiri: React DI-BUNDLE sendiri (tidak memakai SDK dashboard).
// Build keluar ke ../dist (root mission-control/), di-serve server.py.
export default defineConfig({
  root: ".",
  plugins: [react()],
  base: "/",
  build: {
    outDir: "../dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});