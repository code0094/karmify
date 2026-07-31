import { useState } from "react";
import type { PushToast } from "../components/Toast";
import type { Playlist, Track } from "../types";

interface InboxViewProps {
  tracks: Track[]; // only unassigned ones
  playlists: Playlist[];
  onAssign: (trackId: number, playlistDbId: number) => Promise<void>;
  push: PushToast;
}

interface Preview {
  trackId: number;
  src: string;
  matched: string;
}

export function InboxView({ tracks, playlists, onAssign, push }: InboxViewProps) {
  const [assigningId, setAssigningId] = useState<number | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewLoadingId, setPreviewLoadingId] = useState<number | null>(null);

  if (tracks.length === 0) {
    return (
      <div className="empty">
        <h3>Инбокс пуст 🎉</h3>
        <p>
          Все лайки разобраны по плейлистам. Новые появятся после «Проверить лайки» — или сами,
          когда поллер заберёт их по расписанию.
        </p>
      </div>
    );
  }

  async function onPreview(track: Track) {
    const search = window.aux?.previewSearch;
    if (!search) {
      push("error", "Предпрослушка работает только внутри приложения");
      return;
    }
    setPreviewLoadingId(track.id);
    try {
      const hit = await search(`${track.artist_name ?? ""} ${track.track_name ?? ""}`.trim());
      if (!hit) {
        push("info", "Превью не нашлось — iTunes не знает этот трек");
        return;
      }
      setPreview({ trackId: track.id, src: hit.previewUrl, matched: hit.matched });
    } catch {
      push("error", "Превью не загрузилось");
    } finally {
      setPreviewLoadingId(null);
    }
  }

  async function assign(track: Track, playlist: Playlist) {
    setAssigningId(track.id);
    try {
      await onAssign(track.id, playlist.id);
    } finally {
      setAssigningId(null);
    }
  }

  return (
    <div className="inbox">
      {tracks.map((track) => (
        <div className="card" key={track.id}>
          <div className="card-head">
            <button
              className="btn-icon"
              onClick={() => onPreview(track)}
              disabled={previewLoadingId === track.id}
              title="Предпрослушка — 30 секунд из iTunes"
            >
              {previewLoadingId === track.id ? "…" : "▶"}
            </button>
            <div className="card-title">
              <strong>{track.artist_name ?? "?"}</strong> — {track.track_name ?? "?"}
              <span className="dim"> · лайк от {track.liked_by}</span>
            </div>
            {track.detected_genre ? (
              <span className="tag">
                🏷 {track.detected_genre} <span className="dim">({track.genre_source})</span>
              </span>
            ) : (
              <span className="tag dim">жанр не определён — выбери руками</span>
            )}
          </div>

          {preview?.trackId === track.id && (
            <div className="preview-row">
              <audio controls autoPlay src={preview.src} />
              <span className="dim">iTunes: {preview.matched}</span>
            </div>
          )}

          <div className="genre-row">
            {playlists.map((p) => {
              const suggested = p.genre_key === track.detected_genre;
              return (
                <button
                  key={p.id}
                  className={suggested ? "btn suggested" : "btn"}
                  disabled={assigningId === track.id}
                  onClick={() => assign(track, p)}
                >
                  {p.emoji} {p.display_name}
                  {suggested ? " ✨" : ""}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
