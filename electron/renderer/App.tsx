import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { LibraryTable } from "./components/LibraryTable";
import { Player } from "./components/Player";
import { SearchBar } from "./components/SearchBar";
import type { Playlist, SearchResult, Track } from "./types";

const SIDECAR = window.aux?.sidecarUrl ?? "http://127.0.0.1:8765";

export function App() {
  const [tracks, setTracks] = useState<Track[]>([]);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [playerSrc, setPlayerSrc] = useState<string | null>(null);
  const [sources, setSources] = useState<string[]>(["spotify"]);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    const [t, p] = await Promise.all([api.listTracks(), api.listPlaylists()]);
    setTracks(t);
    setPlaylists(p);
  }, []);

  useEffect(() => {
    reload().catch((e) => console.error(e));
    fetch(`${SIDECAR}/health`)
      .then((r) => r.json())
      .then((d: { sources?: string[] }) => setSources(d.sources ?? ["spotify"]))
      .catch(() => undefined);
  }, [reload]);

  async function onFetchLikes() {
    setBusy(true);
    try {
      const r = await api.fetchLikes();
      await reload();
      alert(`Новых треков: ${r.new}`);
    } catch (e) {
      alert(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onAssign(trackId: number, playlistDbId: number) {
    try {
      await api.assign(trackId, playlistDbId);
      await reload();
    } catch (e) {
      alert(String(e));
    }
  }

  async function onDownload(trackId: number) {
    try {
      await api.download(trackId);
      await reload();
    } catch (e) {
      alert(String(e));
    }
  }

  function onPlay(track: Track) {
    if (track.download_path) {
      setPlayerSrc(`file://${track.download_path.replace(/\\/g, "/")}`);
    }
  }

  async function onDownloadResult(result: SearchResult) {
    try {
      const r = await api.downloadResult(result);
      alert(`Скачано: ${r.path}`);
    } catch (e) {
      alert(String(e));
    }
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        color: "#ddd",
        background: "#121212",
        fontFamily: "sans-serif",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: 12,
          borderBottom: "1px solid #333",
        }}
      >
        <strong>AUX MASTERS</strong>
        <button onClick={onFetchLikes} disabled={busy}>
          {busy ? "…" : "🔄 Проверить лайки"}
        </button>
      </header>

      <SearchBar sources={sources} onResults={setResults} />

      {results.length > 0 && (
        <div style={{ padding: 12, borderBottom: "1px solid #333", maxHeight: 200, overflow: "auto" }}>
          <h4 style={{ margin: "0 0 8px" }}>Результаты поиска</h4>
          {results.map((r, i) => (
            <div key={`${r.source}-${i}`} style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ flex: 1 }}>
                [{r.source}] {r.artist} — {r.title}
                {r.audio_format
                  ? ` (${r.audio_format}${r.bitrate ? ` ${r.bitrate}kbps` : ""})`
                  : ""}
              </span>
              <button onClick={() => onDownloadResult(r)}>⬇</button>
            </div>
          ))}
        </div>
      )}

      <main style={{ flex: 1, overflow: "auto" }}>
        <LibraryTable
          tracks={tracks}
          playlists={playlists}
          onAssign={onAssign}
          onDownload={onDownload}
          onPlay={onPlay}
        />
      </main>

      <Player src={playerSrc} />
    </div>
  );
}
