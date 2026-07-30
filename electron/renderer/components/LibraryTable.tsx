import type { Playlist, Track } from "../types";

interface LibraryTableProps {
  tracks: Track[];
  playlists: Playlist[];
  onAssign: (trackId: number, playlistDbId: number) => void;
  onDownload: (trackId: number) => void;
  onPlay: (track: Track) => void;
}

const cell: React.CSSProperties = { padding: "4px 8px", borderBottom: "1px solid #2a2a2a" };

export function LibraryTable({
  tracks,
  playlists,
  onAssign,
  onDownload,
  onPlay,
}: LibraryTableProps) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <thead>
        <tr style={{ textAlign: "left", color: "#aaa" }}>
          <th style={cell}>Артист — Трек</th>
          <th style={cell}>Жанр</th>
          <th style={cell}>Кто</th>
          <th style={cell}>Плейлист</th>
          <th style={cell}>Действия</th>
        </tr>
      </thead>
      <tbody>
        {tracks.map((t) => (
          <tr key={t.id}>
            <td style={cell}>
              {t.artist_name} — {t.track_name}
            </td>
            <td style={cell}>
              {t.detected_genre ?? "—"}
              {t.genre_source ? ` (${t.genre_source})` : ""}
            </td>
            <td style={cell}>{t.liked_by}</td>
            <td style={cell}>
              <select
                value=""
                onChange={(e) => e.target.value && onAssign(t.id, Number(e.target.value))}
              >
                <option value="" disabled>
                  {t.assigned_playlist_id ? "переназначить…" : "выбрать…"}
                </option>
                {playlists.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.emoji} {p.display_name}
                  </option>
                ))}
              </select>
            </td>
            <td style={cell}>
              <button
                disabled={!t.download_path}
                title={t.download_path ?? "сначала скачай"}
                onClick={() => onPlay(t)}
              >
                ▶
              </button>{" "}
              <button onClick={() => onDownload(t.id)}>
                {t.downloaded_at ? "✅" : "⬇"}
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
