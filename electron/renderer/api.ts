import type { Crew, Playlist, SearchResult, Track, TrackFilters } from "./types";

export interface PreviewHit {
  previewUrl: string;
  matched: string;
}

declare global {
  interface Window {
    aux?: {
      sidecarUrl: string;
      sidecarToken?: string;
      // Bridged to the Electron main process (absent when served outside Electron).
      previewSearch?: (term: string) => Promise<PreviewHit | null>;
    };
  }
}

const BASE = window.aux?.sidecarUrl ?? "http://127.0.0.1:8765";
const TOKEN = window.aux?.sidecarToken ?? "";

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body) headers["Content-Type"] = "application/json";
  if (TOKEN) headers["X-Aux-Token"] = TOKEN;

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}

export function audioUrl(trackId: number): string {
  // <audio src> cannot send the X-Aux-Token header — the token rides as a query param.
  const qs = TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : "";
  return `${BASE}/tracks/${trackId}/audio${qs}`;
}

export function spotifyLoginUrl(user: string): string {
  // Opened as a top-level navigation, so the token cannot travel in a header.
  const qs = TOKEN ? `&token=${encodeURIComponent(TOKEN)}` : "";
  return `${BASE}/auth/spotify/login?user=${encodeURIComponent(user)}${qs}`;
}

export const api = {
  crew(): Promise<Crew> {
    return request<Crew>("GET", "/crew");
  },
  listTracks(filters: TrackFilters = {}): Promise<Track[]> {
    const params = new URLSearchParams();
    if (filters.genre) params.set("genre", filters.genre);
    if (filters.liked_by) params.set("liked_by", filters.liked_by);
    if (filters.only_undownloaded) params.set("only_undownloaded", "true");
    const qs = params.toString();
    return request<Track[]>("GET", `/tracks${qs ? `?${qs}` : ""}`);
  },
  listPlaylists(): Promise<Playlist[]> {
    return request<Playlist[]>("GET", "/playlists");
  },
  fetchLikes(): Promise<{ new: number }> {
    return request<{ new: number }>("POST", "/likes/fetch");
  },
  assign(trackId: number, playlistDbId: number): Promise<{ added: boolean }> {
    return request("POST", `/tracks/${trackId}/assign`, { playlist_db_id: playlistDbId });
  },
  downloadPlaylist(playlistDbId: number): Promise<{ queued: number }> {
    return request("POST", `/playlists/${playlistDbId}/download`);
  },
  initPlaylists(): Promise<{ created: number; skipped: number }> {
    return request("POST", "/playlists/init");
  },
  search(query: string, source = "spotify", limit = 20): Promise<SearchResult[]> {
    return request("POST", "/sources/search", { query, source, limit });
  },
  downloadResult(result: SearchResult): Promise<{ path: string }> {
    return request("POST", "/sources/download", { result });
  },
};
