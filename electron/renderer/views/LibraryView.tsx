import { Download, Loader, Play, TriangleAlert } from "lucide-react";
import {
  FormatBadge,
  Swatch,
  formatOf,
  hueOf,
  playlistOfTrack,
} from "../components/primitives";
import type { Playlist, Track } from "../types";

interface LibraryViewProps {
  tracks: Track[];
  playlists: Playlist[];
  /** Playlist filter picked in the rail (genre_key), or null for everything. */
  filter: string | null;
  spotifyConnected: boolean;
  onPlay: (track: Track) => void;
  onDownloadPlaylist: (playlistDbId: number) => Promise<void>;
  onInitPlaylists: () => Promise<void>;
}

const COLUMNS = "34px 1fr 110px 190px 150px";

/** Where the file came from — the redesign's key addition to the library. */
function FileCell({ track }: { track: Track }) {
  if (track.downloaded_at) {
    const format = formatOf(track.download_path);
    return (
      <span className="origin" title={track.download_path ?? ""}>
        {format && <FormatBadge format={format} />}
        <span className="ellipsis">{track.download_source ?? ""}</span>
      </span>
    );
  }
  if (track.download_started_at) {
    return (
      <span className="state-busy">
        <Loader size={13} strokeWidth={1.75} />
        качается…
      </span>
    );
  }

  if (track.last_download_error) {
    // The reason lives in the tooltip: an error string in the row would wreck it.
    return (
      <span className="state-err" title={track.last_download_error}>
        <TriangleAlert size={13} strokeWidth={1.75} />
        не вышло
      </span>
    );
  }
  return <span className="dim">—</span>;
}

export function LibraryView({
  tracks,
  playlists,
  filter,
  spotifyConnected,
  onPlay,
  onDownloadPlaylist,
  onInitPlaylists,
}: LibraryViewProps) {
  if (playlists.length === 0) {
    return (
      <div className="view">
        <div className="empty">
          <h3>Плейлистов пока нет</h3>
          <p>
            {spotifyConnected
              ? "Создай стандартный набор жанров — Hardgroove, Rave Techno, Electro, Acid, Jungle. Они появятся и здесь, и в Spotify."
              : "Сначала авторизуй Spotify — чип с аккаунтом вверху справа. Потом здесь появится кнопка создания плейлистов."}
          </p>
          {spotifyConnected && (
            <button className="btn btn-accent" onClick={onInitPlaylists}>
              Создать плейлисты
            </button>
          )}
        </div>
      </div>
    );
  }

  const selected = filter ? playlists.find((p) => p.genre_key === filter) : undefined;
  const rows = selected
    ? tracks.filter((t) => t.assigned_playlist_id === selected.playlist_id)
    : tracks;
  const missing = selected ? selected.total_tracks - selected.downloaded : 0;

  return (
    <div className="view">
      <div className="toolbar">
        <span className="label-caps">Библиотека</span>
        <span className="dim" style={{ fontSize: 13 }}>
          {rows.length} треков{selected ? ` · ${selected.display_name}` : ""}
        </span>
        <span className="spacer" />
        {selected && selected.downloading > 0 && (
          <span className="state-busy">
            <Loader size={13} strokeWidth={1.75} />
            качаю {selected.downloaded}/{selected.total_tracks}
          </span>
        )}
        {selected && missing > 0 && selected.downloading === 0 && (
          <button className="btn btn-accent" onClick={() => onDownloadPlaylist(selected.id)}>
            <Download size={14} strokeWidth={1.75} />
            Скачать недостающие ({missing})
          </button>
        )}
      </div>

      {rows.length === 0 ? (
        <div className="empty">
          <h3>Здесь пока пусто</h3>
          <p>
            {selected
              ? "В этом плейлисте нет треков — разбери инбокс, и они появятся."
              : "Разобранные треки появятся здесь после инбокса."}
          </p>
        </div>
      ) : (
        <>
          <div className="thead" style={{ gridTemplateColumns: COLUMNS }}>
            <span />
            <span className="label-caps">Артист — трек</span>
            <span className="label-caps">Кто</span>
            <span className="label-caps">Файл</span>
            <span className="label-caps">Плейлист</span>
          </div>

          {rows.map((track) => {
            const playlist = playlistOfTrack(track, playlists);
            return (
              <div key={track.id} className="trow compact" style={{ gridTemplateColumns: COLUMNS }}>
                <button
                  className="icon-btn"
                  disabled={!track.download_path}
                  onClick={() => onPlay(track)}
                  title={track.download_path ? "Слушать" : "Сначала скачай"}
                >
                  <Play size={12} strokeWidth={1.75} />
                </button>

                <div className="title-cell">
                  <span className="artist">{track.artist_name ?? "?"}</span>
                  <span className="track">{track.track_name ?? "?"}</span>
                </div>

                <span className="meta-cell">{track.liked_by}</span>
                <FileCell track={track} />

                <span className="meta-cell" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {playlist && <Swatch hue={hueOf(playlist)} size={6} />}
                  {playlist?.display_name ?? ""}
                </span>
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
