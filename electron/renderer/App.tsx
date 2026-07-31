import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, audioUrl, spotifyLoginUrl } from "./api";
import { Player, type NowPlaying } from "./components/Player";
import { ToastStack, type ToastKind, type ToastMsg } from "./components/Toast";
import { InboxView } from "./views/InboxView";
import { LibraryView } from "./views/LibraryView";
import { SearchView } from "./views/SearchView";
import type { Playlist, Track } from "./types";

const SIDECAR = window.aux?.sidecarUrl ?? "http://127.0.0.1:8765";

type View = "inbox" | "library" | "search";

export function App() {
  const [view, setView] = useState<View>("inbox");
  const [tracks, setTracks] = useState<Track[]>([]);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [accounts, setAccounts] = useState<Record<string, boolean>>({});
  const [sources, setSources] = useState<string[]>([]);
  const [busyLikes, setBusyLikes] = useState(false);
  const [playing, setPlaying] = useState<NowPlaying | null>(null);
  const [toasts, setToasts] = useState<ToastMsg[]>([]);
  const toastSeq = useRef(0);

  const push = useCallback((kind: ToastKind, text: string) => {
    toastSeq.current += 1;
    setToasts((prev) => [...prev, { id: toastSeq.current, kind, text }]);
  }, []);
  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const reload = useCallback(async () => {
    const [t, p] = await Promise.all([api.listTracks(), api.listPlaylists()]);
    setTracks(t);
    setPlaylists(p);
  }, []);

  useEffect(() => {
    reload().catch(() => push("error", "Бэкенд недоступен — проверь туннель до сайдкара"));
    api
      .spotifyStatus()
      .then(setAccounts)
      .catch(() => undefined);
    fetch(`${SIDECAR}/health`)
      .then((r) => r.json())
      .then((d: { sources?: string[] }) => setSources(d.sources ?? []))
      .catch(() => undefined);
  }, [reload, push]);

  // Fire-and-poll: while anything is downloading, refresh so ⏳ turns into ✓.
  const downloadsRunning =
    playlists.some((p) => p.downloading > 0) ||
    tracks.some((t) => t.download_started_at && !t.downloaded_at);
  useEffect(() => {
    if (!downloadsRunning) return;
    const timer = setInterval(() => {
      reload().catch(() => undefined);
    }, 5000);
    return () => clearInterval(timer);
  }, [downloadsRunning, reload]);

  const inbox = useMemo(() => tracks.filter((t) => !t.assigned_playlist_id), [tracks]);
  const assigned = useMemo(() => tracks.filter((t) => t.assigned_playlist_id), [tracks]);

  async function onFetchLikes() {
    setBusyLikes(true);
    try {
      const r = await api.fetchLikes();
      await reload();
      push(r.new > 0 ? "success" : "info", r.new > 0 ? `Новых лайков: ${r.new}` : "Нового ничего");
      if (r.new > 0) setView("inbox");
    } catch (err) {
      push("error", `Не получилось забрать лайки: ${String(err)}`);
    } finally {
      setBusyLikes(false);
    }
  }

  async function onAssign(trackId: number, playlistDbId: number) {
    const playlist = playlists.find((p) => p.id === playlistDbId);
    try {
      await api.assign(trackId, playlistDbId);
      await reload();
      push("success", `Добавлено в ${playlist ? playlist.display_name : "плейлист"}`);
    } catch (err) {
      push("error", `Не назначилось: ${String(err)}`);
    }
  }

  async function onDownloadPlaylist(playlistDbId: number) {
    try {
      const r = await api.downloadPlaylist(playlistDbId);
      if (r.queued === 0) push("info", "Всё уже скачано");
      else push("success", `В очереди ${r.queued} — качаю в фоне, можно работать дальше`);
      await reload();
    } catch (err) {
      push("error", `Скачивание не запустилось: ${String(err)}`);
    }
  }

  function onConnectSpotify(user: string) {
    // Consent happens in the real browser: Electron's window is not a place to
    // type Spotify credentials, and Spotify blocks embedded webviews anyway.
    window.open(spotifyLoginUrl(user), "_blank", "noopener");
    // The status only changes once the user finishes in the browser.
    setTimeout(() => {
      api
        .spotifyStatus()
        .then(setAccounts)
        .catch(() => undefined);
    }, 5000);
  }

  function onPlay(track: Track) {
    if (!track.download_path) return;
    setPlaying({
      src: audioUrl(track.id),
      label: `${track.artist_name ?? "?"} — ${track.track_name ?? "?"}`,
    });
  }

  return (
    <div className="app">
      <header className="header">
        <span className="logo">KARMIFY</span>
        <button className="btn" onClick={onFetchLikes} disabled={busyLikes}>
          {busyLikes ? "Проверяю…" : "🔄 Проверить лайки"}
        </button>
        <span className="spacer" />
        {Object.entries(accounts).map(([user, connected]) => (
          <button
            key={user}
            className={connected ? "chip chip-ok" : "chip"}
            onClick={() => onConnectSpotify(user)}
            title={
              connected
                ? `Spotify ${user} подключён — нажми, чтобы переподключить`
                : `Spotify ${user} не подключён — нажми, чтобы авторизоваться`
            }
          >
            <span className={connected ? "dot dot-ok" : "dot"} /> {user}
          </button>
        ))}
      </header>

      <nav className="nav">
        <button
          className={view === "inbox" ? "nav-item active" : "nav-item"}
          onClick={() => setView("inbox")}
        >
          📥 Разбор
          {inbox.length > 0 && <span className="badge">{inbox.length}</span>}
        </button>
        <button
          className={view === "library" ? "nav-item active" : "nav-item"}
          onClick={() => setView("library")}
        >
          🎛 Библиотека
        </button>
        <button
          className={view === "search" ? "nav-item active" : "nav-item"}
          onClick={() => setView("search")}
        >
          🔍 Поиск
        </button>
      </nav>

      <main className="content">
        {view === "inbox" && (
          <InboxView tracks={inbox} playlists={playlists} onAssign={onAssign} push={push} />
        )}
        {view === "library" && (
          <LibraryView
            playlists={playlists}
            tracks={assigned}
            onPlay={onPlay}
            onAssign={onAssign}
            onDownloadPlaylist={onDownloadPlaylist}
          />
        )}
        {view === "search" && <SearchView sources={sources} push={push} />}
      </main>

      <Player playing={playing} />
      <ToastStack toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
