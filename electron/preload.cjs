// Preload (CommonJS): expose the sidecar URL to the renderer safely.
const { contextBridge } = require("electron");

const host = process.env.AUX_SIDECAR_HOST || "127.0.0.1";
const port = process.env.AUX_SIDECAR_PORT || "8765";

contextBridge.exposeInMainWorld("aux", {
  sidecarUrl: `http://${host}:${port}`,
});
