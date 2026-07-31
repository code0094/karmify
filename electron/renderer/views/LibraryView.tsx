import { useState } from "react";
import type { Playlist, Track } from "../types";

interface LibraryViewProps {
  playlists: Playlist[];
  tracks: Track[]; // only assigned ones
  onPlay: (track: Track) => void;
  onAssign: (trackId: number, playlistDbId: number) => Promise<void>;
  onDownloadPlaylist: (playlistDbId: number) => Promise<void>;
}

const LOSSLESS = new Set(["flac", "wav", "aiff", "aif", "alac"]);

function fileExt(path: string | null): string | null {
  if (!path) return null;
  const dot = path.lastIndexOf(".");
  return dot === -1 ? null : path.slice(dot + 1).toLowerCase();
}

function FormatBadge({ path }: { path: string | null }) {
  const ext = fileExt(path);
  if (!ext) return null;
  return <span className={LOSSLESS.has(ext) ? "fmt fmt-lossless" : "fmt"}>{ext}</span>;
}

function StatusCell({ track }: { track: Track }) {
  if (track.downloaded_at) {
    return (
      <span className="status-ok" title={track.download_path ?? ""}>
        ✓ скачан <FormatBadge path={track.download_path} />
      </span>
    );
  }
  if (track.download_started_at) return <span className="status-busy">⏳ качается…</span>;
  if (track.last_download_error) {
    return (
      <span className="status-err" title={track.last_download_error}>
        ✗ не вышло
      </span>
    );
  }
  return <span className="dim">—</span>;
}

export function LibraryView({
  playlists,
  tracks,
  onPlay,
  onAssign,
  onDownloadPlaylist,
}: LibraryViewProps) {
  const [selectedId, setSelectedId] = useState<number | null>(null);

  if (playlists.length === 0) {
    return (
      <div className="empty">
        <h3>Плейлистов пока нет</h3>
        <p>
          Жанровые плейлисты создаются один раз скриптом <code>scripts/init_playlists.py</code> —
          после этого здесь появится библиотека.
        </p>
      </div>
    );
  }

  const selected = playlists.find((p) => p.id === selectedId) ?? null;
  const rows = selected
    ? tracks.filter((t) => t.assigned_playlist_id === selected.playlist_id)
    : tracks;
  const remaining = selected ? selected.total_tracks - selected.downloaded : 0;

  return (
    <div className="library">
      <div className="playlist-list">
        <button
          className={selected === null ? "playlist-item active" : "playlist-item"}
          onClick={() => setSelectedId(null)}
        >
          <span className="playlist-name">Все треки</span>
          <span className="playlist-progress">{tracks.length}</span>
        </button>
        {playlists.map((p) => {
          const complete = p.total_tracks > 0 && p.downloaded === p.total_tracks;
          return (
            <button
              key={p.id}
              className={p.id === selectedId ? "playlist-item active" : "playlist-item"}
              onClick={() => setSelectedId(p.id)}
            >
              <span>{p.emoji}</span>
              <span className="playlist-name">{p.display_name}</span>
              <span
                className={complete ? "playlist-progress complete" : "playlist-progress"}
                title={p.failed > 0 ? `${p.failed} с ошибкой` : undefined}
              >
                {p.downloading > 0 && "⏳ "}
                {p.failed > 0 && "✗ "}
                {p.total_tracks === 0 ? "—" : `${p.downloaded}/${p.total_tracks}`}
              </span>
            </button>
          );
        })}
      </div>

      <div className="library-main">
        {selected && (
          <div className="library-toolbar">
            <strong>
              {selected.emoji} {selected.display_name}
            </strong>
            {selected.downloading > 0 ? (
              <button className="btn" disabled>
                ⏳ Качается… {selected.downloaded}/{selected.total_tracks}
              </button>
            ) : remaining > 0 ? (
              <button className="btn btn-accent" onClick={() => onDownloadPlaylist(selected.id)}>
                ⬇ Скачать плейлист ({remaining})
              </button>
            ) : selected.total_tracks > 0 ? (
              <span className="status-ok">✓ скачан полностью</span>
            ) : null}
            {selected.failed > 0 && (
              <span className="status-err">
                {selected.failed} не скачалось — наведи на ✗ в списке, чтобы узнать почему
              </span>
            )}
          </div>
        )}

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
          <table className="table">
            <thead>
              <tr>
                <th></th>
                <th>Артист — Трек</th>
                <th>Кто</th>
                <th>Статус</th>
                <th>Плейлист</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id}>
                  <td>
                    <button
                      className="btn-icon"
                      disabled={!t.download_path}
                      title={t.download_path ? "Слушать" : "Сначала скачай"}
                      onClick={() => onPlay(t)}
                    >
                      ▶
                    </button>
                  </td>
                  <td>
                    <strong>{t.artist_name ?? "?"}</strong> — {t.track_name ?? "?"}
                  </td>
                  <td className="dim">{t.liked_by}</td>
                  <td>
                    <StatusCell track={t} />
                  </td>
                  <td>
                    <select
                      value=""
                      title="Переназначить в другой плейлист"
                      onChange={(e) => e.target.value && onAssign(t.id, Number(e.target.value))}
                    >
                      <option value="" disabled>
                        переназначить…
                      </option>
                      {playlists
                        .filter((p) => p.playlist_id !== t.assigned_playlist_id)
                        .map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.emoji} {p.display_name}
                          </option>
                        ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
