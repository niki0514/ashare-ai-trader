import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const serverHost = process.env.VITE_HOST ?? "127.0.0.1";
const serverPort = Number(process.env.VITE_PORT ?? "5174");
const usePolling = process.env.VITE_USE_POLLING === "true";
const hmrHost = process.env.VITE_HMR_HOST;
const hmrPort = process.env.VITE_HMR_PORT
  ? Number(process.env.VITE_HMR_PORT)
  : serverPort;

export default defineConfig({
  plugins: [react()],
  server: {
    host: serverHost,
    port: serverPort,
    strictPort: true,
    watch: usePolling
      ? {
          usePolling: true,
          interval: 300,
        }
      : undefined,
    hmr: hmrHost
      ? {
          host: hmrHost,
          port: hmrPort,
        }
      : undefined,
    proxy: {
      "/api": {
        target: process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:3101",
        changeOrigin: true,
      },
    },
  }
});
