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
    // Bind IPv4 explicitly: "localhost" alone leaves Vite on [::1], while
    // Electron and Node resolve localhost to 127.0.0.1 and get refused.
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
  },
});
