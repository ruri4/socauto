import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

const apiProxy = {
  target: "http://127.0.0.1:8000",
  changeOrigin: false,
};

export default defineConfig({
  plugins: [svelte()],
  server: {
    host: "127.0.0.1",
    proxy: {
      "/health": apiProxy,
      "/v1": apiProxy,
    },
  },
  preview: {
    host: "127.0.0.1",
    proxy: {
      "/health": apiProxy,
      "/v1": apiProxy,
    },
  },
});
