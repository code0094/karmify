import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// base: "./" so the built index.html uses relative asset paths (Electron loadFile).
export default defineConfig({
  root: ".",
  base: "./",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
  },
});
