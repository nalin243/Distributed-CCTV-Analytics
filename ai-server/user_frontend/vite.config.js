import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    // During development, proxy API/media requests to the Flask backend
    // so you don't need CORS headers locally.
    proxy: {
      "/api":   { target: "http://192.168.1.16:5000", changeOrigin: true },
      "/image": { target: "http://192.168.1.16:5000", changeOrigin: true },
      "/video": { target: "http://192.168.1.16:5000", changeOrigin: true },
    },
  },
});