import { CheckCheck, Play } from "lucide-react";
import { useMemo, useState } from "react";
import { PlaylistMenu } from "../components/PlaylistMenu";
import { PlaylistPick } from "../components/PlaylistPick";
import { hueOf } from "../components/primitives";
import type { PushToast } from "../components/Toast";
import type { Playlist, Track } from "../types";

/** Filing pairs — one track to one playlist; a single file is a batch of one. */
export type FilePair = { track: Track; playlist: Playlist };

interface InboxViewProps {
  tracks: Track[];
  playlists: Playlist[];
  onFile: (pairs: FilePair[]) => Promise<void>;
  onCreateAndFile: (displayName: string, tracks: Track[]) => Promise<void>;
  onDragTrack: (track: Track | null) => void;
  push: PushToast;
}

const COLUMNS = "26px 32px minmax(150px,1fr) 130px 78px 100px 384px";

export function InboxView({
  tracks,
  playlists,
  onFile,
  onCreateAndFile,
  onDragTrack,
  push,
}: InboxViewProps) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [previewing, setPreviewing] = useState<number | null>(null);
  const [preview, setPreview] = useState<{ trackId: number; src: string } | null>(null);

  const byGenre = useMemo(
    () => new Map(playlists.map((p) => [p.genre_key, p])),
    [playlists],
  );

  /** The guess first, then the crew's most-used playlists, capped at three. */
  function picksFor(track: Track): Playlist[] {
    const guess = track.detected_genre ? byGenre.get(track.detected_genre) : undefined;
    const rest = playlists
      .filter((p) => p.id !== guess?.id)
      .slice()
      .sort((a, b) => b.total_tracks - a.total_tracks);
    return [guess, ...rest].filter((p): p is Playlist => Boolean(p)).slice(0, 3);
  }

  const resolved = tracks.filter((t) => t.detected_genre && byGenre.has(t.detected_genre));

  if (tracks.length === 0) {
    return (
      <div className="view">
        <div className="empty">
          <h3>Все плейлисты собраны</h3>
          <p>Новые лайки появятся сами, когда поллер заберёт их.</p>
        </div>
      </div>
    );
  }

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function fileOne(track: Track, playlist: Playlist) {
    await onFile([{ track, playlist }]);
  }

  async function fileSelected(playlist: Playlist) {
    const chosen = tracks.filter((t) => selected.has(t.id));
    setSelected(new Set());
    await onFile(chosen.map((track) => ({ track, playlist })));
  }

  async function acceptAllGuesses() {
    const pairs = resolved
      .map((track) => ({ track, playlist: byGenre.get(track.detected_genre!)! }))
      .filter((p) => p.playlist);
    await onFile(pairs);
  }

  async function playPreview(track: Track) {
    const search = window.aux?.previewSearch;
    if (!search) {
      push("error", "Предпрослушка работает только внутри приложения");
      return;
    }
    setPreviewing(track.id);
    try {
      const hit = await search(`${track.artist_name ?? ""} ${track.track_name ?? ""}`.trim());
      if (!hit) {
        push("info", "Превью не нашлось — iTunes не знает этот трек");
        return;
      }
      setPreview({ trackId: track.id, src: hit.previewUrl });
    } catch {
      push("error", "Превью не загрузилось");
    } finally {
      setPreviewing(null);
    }
  }

  return (
    <div className="view">
      <div className="toolbar">
        <span className="label-caps">Разбор</span>
        <span className="dim" style={{ fontSize: 13 }}>
          {tracks.length} лайка ждут плейлиста
        </span>
        <span className="spacer" />
        {resolved.length > 0 && (
          <button className="btn btn-accent" onClick={acceptAllGuesses}>
            <CheckCheck size={14} strokeWidth={1.75} />
            Принять все догадки ({resolved.length})
          </button>
        )}
      </div>

      <div className="thead" style={{ gridTemplateColumns: COLUMNS }}>
        <span />
        <span />
        <span className="label-caps">Артист — трек</span>
        <span className="label-caps">Лейбл</span>
        <span className="label-caps">Кто</span>
        <span className="label-caps">Догадка</span>
        <span className="label-caps" style={{ justifySelf: "end" }}>
          Плейлист
        </span>
      </div>

      {tracks.map((track) => {
        const guess = track.detected_genre ? byGenre.get(track.detected_genre) : undefined;
        const isSelected = selected.has(track.id);
        return (
          <div
            key={track.id}
            className={isSelected ? "trow inbox selected" : "trow inbox"}
            style={{ gridTemplateColumns: COLUMNS }}
            draggable
            onDragStart={() => onDragTrack(track)}
            onDragEnd={() => onDragTrack(null)}
          >
            <button
              className={isSelected ? "check on" : "check"}
              onClick={() => toggle(track.id)}
              title="Выбрать"
            >
              ✓
            </button>

            <button
              className="icon-btn"
              disabled={previewing === track.id}
              onClick={() => playPreview(track)}
              title="Предпрослушка — 30 секунд из iTunes"
            >
              <Play size={12} strokeWidth={1.75} />
            </button>

            <div className="title-cell">
              <span className="artist">{track.artist_name ?? "?"}</span>
              <span className="track">{track.track_name ?? "?"}</span>
            </div>

            <span className="meta-cell">{track.record_label ?? ""}</span>
            <span className="meta-cell">{track.liked_by}</span>

            {guess ? (
              <span
                className="guess"
                style={{ background: `${hueOf(guess)}1f`, color: hueOf(guess) }}
                title={`${guess.display_name} — определил ${track.genre_source}`}
              >
                <span className="sq" style={{ background: hueOf(guess) }} />
                {track.genre_source}
              </span>
            ) : (
              <span className="guess-none">не определён</span>
            )}

            <div className="pick-group">
              {picksFor(track).map((p) => (
                <PlaylistPick
                  key={p.id}
                  playlist={p}
                  suggested={p.id === guess?.id}
                  onPick={(pl) => fileOne(track, pl)}
                />
              ))}
              <PlaylistMenu
                playlists={playlists}
                suggested={track.detected_genre}
                onPick={(pl) => fileOne(track, pl)}
                onCreate={(name) => onCreateAndFile(name, [track])}
              />
            </div>

            {preview?.trackId === track.id && (
              // eslint-disable-next-line jsx-a11y/media-has-caption
              <audio autoPlay src={preview.src} style={{ display: "none" }} />
            )}
          </div>
        );
      })}

      {selected.size > 0 && (
        <div className="multibar">
          <span style={{ fontSize: 13, fontWeight: 600 }}>Выбрано {selected.size}</span>
          <span className="divider-v" />
          <span className="label-caps">В плейлист</span>
          <div className="pick-group always">
            {playlists.slice(0, 4).map((p) => (
              <PlaylistPick key={p.id} playlist={p} width={118} onPick={fileSelected} />
            ))}
            <PlaylistMenu
              playlists={playlists}
              onPick={fileSelected}
              onCreate={(name) =>
                onCreateAndFile(
                  name,
                  tracks.filter((t) => selected.has(t.id)),
                )
              }
            />
          </div>
          <span className="spacer" />
          <button className="btn btn-ghost" onClick={() => setSelected(new Set())}>
            Снять выделение
          </button>
        </div>
      )}
    </div>
  );
}
