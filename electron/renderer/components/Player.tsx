interface PlayerProps {
  src: string | null;
}

export function Player({ src }: PlayerProps) {
  return (
    <div style={{ borderTop: "1px solid #333", padding: "8px 12px", background: "#1a1a1a" }}>
      {src ? (
        <audio controls autoPlay src={src} style={{ width: "100%" }} />
      ) : (
        <span style={{ color: "#888" }}>Выбери скачанный трек, чтобы прослушать</span>
      )}
    </div>
  );
}
