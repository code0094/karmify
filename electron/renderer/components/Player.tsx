import { Play } from "lucide-react";
import { FormatBadge, formatOf } from "./primitives";

export interface NowPlaying {
  src: string;
  label: string;
  /** Where the file came from, shown under the title. */
  path: string | null;
}

interface PlayerProps {
  playing: NowPlaying | null;
}

export function Player({ playing }: PlayerProps) {
  const format = playing ? formatOf(playing.path) : null;

  return (
    <div className="player">
      <button className="icon-btn player" disabled={!playing} title="Играет">
        <Play size={14} strokeWidth={1.75} fill="currentColor" />
      </button>

      {playing ? (
        <>
          <div className="player-meta">
            <span className="now" title={playing.label}>
              {playing.label}
            </span>
            {format && (
              <span className="origin">
                <FormatBadge format={format} />
              </span>
            )}
          </div>
          {/* The app keeps the native transport rather than a bespoke scrubber. */}
          <audio controls autoPlay src={playing.src} />
        </>
      ) : (
        <span className="dim" style={{ fontSize: 13 }}>
          Выбери скачанный трек, чтобы прослушать
        </span>
      )}
    </div>
  );
}
