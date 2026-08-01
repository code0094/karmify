/** Small shared pieces: playlist colour, format badge, provenance line. */
import type { Playlist, Track } from "../types";

/** Fallback for playlists created before hues existed (backend owns the real one). */
const HUE_FALLBACK = "#96979d";

export function hueOf(playlist: Playlist | undefined): string {
  return playlist?.hue || HUE_FALLBACK;
}

export function playlistOfTrack(
  track: Track,
  playlists: Playlist[],
): Playlist | undefined {
  return playlists.find((p) => p.playlist_id === track.assigned_playlist_id);
}

export function Swatch({ hue, size = 8 }: { hue: string; size?: number }) {
  return (
    <span
      className="pl-swatch"
      style={{ background: hue, width: size, height: size, borderRadius: size <= 6 ? 2 : 2 }}
    />
  );
}

const LOSSLESS = new Set(["flac", "wav", "aiff", "aif", "alac"]);

export function isLossless(format: string | null | undefined): boolean {
  return LOSSLESS.has((format ?? "").toLowerCase());
}

export function formatOf(path: string | null): string | null {
  if (!path) return null;
  const dot = path.lastIndexOf(".");
  return dot === -1 ? null : path.slice(dot + 1).toLowerCase();
}

/** Green means done AND lossless — the equivalence is the product's thesis. */
export function FormatBadge({ format, bitrate }: { format: string; bitrate?: number | null }) {
  const label = bitrate && !isLossless(format) ? `${format} ${bitrate}` : format;
  return <span className={isLossless(format) ? "fmt lossless" : "fmt"}>{label}</span>;
}

export function humanSize(bytes: number | null | undefined): string {
  return bytes ? `${(bytes / 1048576).toFixed(1)} МБ` : "";
}

export function humanDuration(seconds: number | null | undefined): string {
  if (!seconds) return "";
  const m = Math.floor(seconds / 60);
  const s = String(Math.floor(seconds % 60)).padStart(2, "0");
  return `${m}:${s}`;
}
