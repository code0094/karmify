import type { Playlist } from "../types";
import { Swatch, hueOf } from "./primitives";

interface PlaylistPickProps {
  playlist: Playlist;
  /** The resolver's guess: marked and pre-tinted so one click is the common case. */
  suggested?: boolean;
  width?: number;
  onPick: (playlist: Playlist) => void;
}

/**
 * A one-click filing target. Always the full playlist name — abbreviations
 * ("HG") tested badly.
 */
export function PlaylistPick({ playlist, suggested, width = 113, onPick }: PlaylistPickProps) {
  const hue = hueOf(playlist);
  return (
    <button
      className={suggested ? "pick suggested" : "pick"}
      style={
        suggested
          ? { width, borderColor: hue, color: hue, background: `${hue}1f` }
          : { width }
      }
      onClick={() => onPick(playlist)}
      title={`В плейлист ${playlist.display_name}`}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = hue;
        e.currentTarget.style.color = hue;
      }}
      onMouseLeave={(e) => {
        if (suggested) return;
        e.currentTarget.style.borderColor = "";
        e.currentTarget.style.color = "";
      }}
    >
      <Swatch hue={hue} size={6} />
      <span className="name">{playlist.display_name}</span>
      {suggested && <span style={{ fontSize: 10 }}>✦</span>}
    </button>
  );
}
