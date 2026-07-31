export interface NowPlaying {
  src: string;
  label: string;
}

interface PlayerProps {
  playing: NowPlaying | null;
}

export function Player({ playing }: PlayerProps) {
  return (
    <div className="player-bar">
      {playing ? (
        <>
          <span className="player-label" title={playing.label}>
            {playing.label}
          </span>
          <audio controls autoPlay src={playing.src} />
        </>
      ) : (
        <span className="dim">Выбери скачанный трек, чтобы прослушать</span>
      )}
    </div>
  );
}
