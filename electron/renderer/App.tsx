import { Inbox, LibraryBig, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, audioUrl, spotifyLoginUrl } from "./api";
import { Player, type NowPlaying } from "./components/Player";
import { SourceStatus } from "./components/SourceStatus";
import { ToastStack, type ToastKind, type ToastMsg } from "./components/Toast";
import { Swatch, hueOf } from "./components/primitives";
import { InboxView, type FilePair } from "./views/InboxView";
import { LibraryView } from "./views/LibraryView";
import { SearchView } from "./views/SearchView";
import type { Crew, Playlist, SourceState, Track } from "./types";

type View = "inbox" | "library" | "search";

export function App() {
  const [view, setView] = useState<View>("inbox");
  const [tracks, setTracks] = useState<Track[]>([]);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [crew, setCrew] = useState<Crew | null>(null);
  const [sources, setSources] = useState<SourceState[]>([]);
  const [busyLikes, setBusyLikes] = useState(false);
  const [playing, setPlaying] = useState<NowPlaying | null>(null);
  const [toasts, setToasts] = useState<ToastMsg[]>([]);
  const [dragged, setDragged] = useState<Track | null>(null);
  const [filter, setFilter] = useState<string | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const toastSeq = useRef(0);

  const push = useCallback((kind: ToastKind, text: string) => {
    toastSeq.current += 1;
    const id = toastSeq.current;
    // The same message twice (repeated failures, double effects) is noise.
    setToasts((prev) => (prev.some((t) => t.text === text) ? prev : [...prev, { id, kind, text }]));
  }, []);
  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const reload = useCallback(async () => {
    const [t, p] = await Promise.all([api.listTracks(), api.listPlaylists()]);
    setTracks(t);
    setPlaylists(p);
  }, []);

  const loadEverything = useCallback(async () => {
    await reload();
    api
      .crew()
      .then(setCrew)
      .catch(() => undefined);
    api
      .health()
      .then((h) => setSources(h.sources ?? []))
      .catch(() => undefined);
  }, [reload]);

  useEffect(() => {
    loadEverything().catch(() => {
      setBackendDown(true);
      push("error", "Бэкенд недоступен — проверь туннель до сайдкара");
    });
  }, [loadEverything, push]);

  // The sidecar restarts on every deploy and the SSH tunnel can flap — keep
  // retrying instead of leaving a dead app behind an error toast.
  useEffect(() => {
    if (!backendDown) return;
    const timer = setInterval(() => {
      loadEverything()
        .then(() => {
          setBackendDown(false);
          push("success", "Бэкенд снова на связи");
        })
        .catch(() => undefined);
    }, 10000);
    return () => clearInterval(timer);
  }, [backendDown, loadEverything, push]);

  // Fire-and-poll: while anything downloads, refresh so «качается» becomes a
  // format badge. Source health rides the same poll.
  const downloadsRunning =
    playlists.some((p) => p.downloading > 0) ||
    tracks.some((t) => t.download_started_at && !t.downloaded_at);
  useEffect(() => {
    if (!downloadsRunning) return;
    const timer = setInterval(() => {
      reload().catch(() => undefined);
      api
        .health()
        .then((h) => setSources(h.sources ?? []))
        .catch(() => undefined);
    }, 5000);
    return () => clearInterval(timer);
  }, [downloadsRunning, reload]);

  const inbox = useMemo(() => tracks.filter((t) => !t.assigned_playlist_id), [tracks]);
  const assigned = useMemo(() => tracks.filter((t) => t.assigned_playlist_id), [tracks]);

  /**
   * The single filing path. Every gesture — a pick, the ⋯ menu, multi-select,
   * «Принять все догадки», a drag onto the rail — funnels through here so the
   * optimistic update and the toast stay consistent.
   */
  const fileMany = useCallback(
    async (pairs: FilePair[]) => {
      if (pairs.length === 0) return;
      const ids = new Set(pairs.map((p) => p.track.id));

      // Optimistic: rows leave the inbox now, counters move now.
      setTracks((prev) =>
        prev.map((t) => {
          const pair = pairs.find((p) => p.track.id === t.id);
          return pair ? { ...t, assigned_playlist_id: pair.playlist.playlist_id } : t;
        }),
      );
      setPlaylists((prev) =>
        prev.map((p) => {
          const added = pairs.filter((pair) => pair.playlist.id === p.id).length;
          return added ? { ...p, total_tracks: p.total_tracks + added } : p;
        }),
      );

      if (pairs.length === 1) {
        const { track, playlist } = pairs[0];
        push("success", `${track.artist_name ?? "Трек"} → ${playlist.display_name}`);
      } else {
        push("success", `В очереди ${pairs.length} — качаю в фоне, можно работать дальше`);
      }

      try {
        for (const { track, playlist } of pairs) {
          await api.assign(track.id, playlist.id);
        }
        await reload();
      } catch (err) {
        // Put the rows back: the optimistic move never happened on the server.
        setTracks((prev) =>
          prev.map((t) => (ids.has(t.id) ? { ...t, assigned_playlist_id: null } : t)),
        );
        push("error", `Не разложилось: ${String(err)}`);
        await reload().catch(() => undefined);
      }
    },
    [push, reload],
  );

  const createAndFile = useCallback(
    async (displayName: string, forTracks: Track[]) => {
      try {
        const created = await api.createPlaylist(displayName);
        setPlaylists((prev) => [...prev, created]);
        await fileMany(forTracks.map((track) => ({ track, playlist: created })));
      } catch (err) {
        push("error", `Плейлист не создался: ${String(err)}`);
      }
    },
    [fileMany, push],
  );

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

  async function onInitPlaylists() {
    try {
      const r = await api.initPlaylists();
      await reload();
      push(
        "success",
        r.created > 0 ? `Создано плейлистов: ${r.created}` : "Все плейлисты уже на месте",
      );
    } catch (err) {
      push("error", `Не получилось создать плейлисты: ${String(err)}`);
    }
  }

  async function onDownloadPlaylist(playlistDbId: number) {
    try {
      const r = await api.downloadPlaylist(playlistDbId);
      push(
        r.queued === 0 ? "info" : "success",
        r.queued === 0
          ? "Всё уже скачано"
          : `В очереди ${r.queued} — качаю в фоне, можно работать дальше`,
      );
      await reload();
    } catch (err) {
      push("error", `Скачивание не запустилось: ${String(err)}`);
    }
  }

  function onConnectSpotify(user: string) {
    // Consent happens in the real browser: Spotify blocks embedded webviews,
    // and an Electron window is no place to type credentials anyway.
    window.open(spotifyLoginUrl(user), "_blank", "noopener");
    setTimeout(() => {
      api
        .crew()
        .then(setCrew)
        .catch(() => undefined);
    }, 5000);
  }

  function onPlay(track: Track) {
    if (!track.download_path) return;
    setPlaying({
      src: audioUrl(track.id),
      label: `${track.artist_name ?? "?"} — ${track.track_name ?? "?"}`,
      path: track.download_path,
    });
  }

  function onDropOnPlaylist(playlist: Playlist) {
    if (!dragged) return;
    const track = dragged;
    setDragged(null);
    fileMany([{ track, playlist }]).catch(() => undefined);
  }

  const spotifyConnected = (crew?.members ?? []).some((m) => m.spotify_connected);

  return (
    <div className="app">
      <header className="header">
        <span className="wordmark">Karmify</span>
        <span className="divider-v" />
        {crew?.name && <span className="crew-name">{crew.name}</span>}
        <span className="spacer" />

        <div className="chip-row">
          {(crew?.members ?? []).map((m) => (
            <button
              key={m.label}
              className={m.spotify_connected ? "chip connected" : "chip"}
              onClick={() => onConnectSpotify(m.label)}
              title={
                (m.owner ? "Владелец команды — плейлисты живут на этом Spotify. " : "") +
                (m.spotify_connected
                  ? `Spotify ${m.label} подключён — нажми, чтобы переподключить`
                  : `Spotify ${m.label} не подключён — нажми, чтобы авторизоваться`)
              }
            >
              <span className={m.spotify_connected ? "dot up" : "dot"} />
              {m.owner && <span style={{ color: "var(--flame-500)", fontSize: 11 }}>★</span>}
              {m.display_name}
            </button>
          ))}
        </div>

        <span className="divider-v" />
        <SourceStatus sources={sources} />

        <button className="btn" onClick={onFetchLikes} disabled={busyLikes}>
          <RefreshCw size={14} strokeWidth={1.75} />
          {busyLikes ? "Проверяю…" : "Проверить лайки"}
        </button>
      </header>

      <nav className="rail">
        <div className="rail-group">
          <button
            className={view === "inbox" ? "nav-item active" : "nav-item"}
            onClick={() => setView("inbox")}
          >
            <Inbox size={15} strokeWidth={1.75} />
            <span className="grow">Разбор</span>
            {inbox.length > 0 && <span className="badge">{inbox.length}</span>}
          </button>
          <button
            className={view === "library" ? "nav-item active" : "nav-item"}
            onClick={() => setView("library")}
          >
            <LibraryBig size={15} strokeWidth={1.75} />
            <span className="grow">Библиотека</span>
          </button>
          <button
            className={view === "search" ? "nav-item active" : "nav-item"}
            onClick={() => setView("search")}
          >
            <Search size={15} strokeWidth={1.75} />
            <span className="grow">Поиск</span>
          </button>
        </div>

        {view !== "search" && playlists.length > 0 && (
          <div className="rail-group">
            <span className="label-caps rail-group-label">Плейлисты</span>
            {view === "library" && (
              <button
                className={filter === null ? "pl-target selected" : "pl-target"}
                onClick={() => setFilter(null)}
              >
                <span className="name">Все треки</span>
                <span className="count">{assigned.length}</span>
              </button>
            )}
            {playlists.map((p) => {
              const classes = ["pl-target"];
              if (dragged) classes.push("drop-ready");
              if (view === "library" && filter === p.genre_key) classes.push("selected");
              return (
                <button
                  key={p.id}
                  className={classes.join(" ")}
                  onClick={() =>
                    view === "library" && setFilter(filter === p.genre_key ? null : p.genre_key)
                  }
                  onDragOver={(e) => {
                    if (!dragged) return;
                    e.preventDefault();
                    e.currentTarget.classList.add("drop-hover");
                    e.currentTarget.style.borderColor = hueOf(p);
                    e.currentTarget.style.background = `${hueOf(p)}1f`;
                    e.currentTarget.style.color = hueOf(p);
                  }}
                  onDragLeave={(e) => {
                    e.currentTarget.classList.remove("drop-hover");
                    e.currentTarget.style.borderColor = "";
                    e.currentTarget.style.background = "";
                    e.currentTarget.style.color = "";
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    e.currentTarget.classList.remove("drop-hover");
                    e.currentTarget.style.borderColor = "";
                    e.currentTarget.style.background = "";
                    e.currentTarget.style.color = "";
                    onDropOnPlaylist(p);
                  }}
                  title={
                    view === "library" ? "Фильтр по плейлисту" : "Перетащи сюда трек из разбора"
                  }
                >
                  <Swatch hue={hueOf(p)} />
                  <span className="name">{p.display_name}</span>
                  <span className="count">{p.total_tracks}</span>
                </button>
              );
            })}
          </div>
        )}
      </nav>

      <main className="main">
        {view === "inbox" && (
          <InboxView
            tracks={inbox}
            playlists={playlists}
            onFile={fileMany}
            onCreateAndFile={createAndFile}
            onDragTrack={setDragged}
            push={push}
          />
        )}
        {view === "library" && (
          <LibraryView
            tracks={assigned}
            playlists={playlists}
            filter={filter}
            spotifyConnected={spotifyConnected}
            onPlay={onPlay}
            onDownloadPlaylist={onDownloadPlaylist}
            onInitPlaylists={onInitPlaylists}
          />
        )}
        {view === "search" && <SearchView sources={sources} push={push} />}
      </main>

      <Player playing={playing} />
      <ToastStack toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
