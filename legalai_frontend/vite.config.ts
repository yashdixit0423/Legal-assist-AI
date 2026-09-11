import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// fileURLToPath, not URL.pathname: this project's path contains a space, and
// pathname leaves it percent-encoded as %20, which resolves to nothing.
const clientDir = fileURLToPath(new URL("./client", import.meta.url));

export default defineConfig({
  server: {
    host: "::",
    port: 8080,
  },
  build: {
    outDir: "dist/spa",
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": clientDir,
    },
  },
});
