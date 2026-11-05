import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// dev: React on :5173, API proxied to FastAPI on :8000. build: dist/ is served by FastAPI.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "dist", chunkSizeWarningLimit: 800 },
});
