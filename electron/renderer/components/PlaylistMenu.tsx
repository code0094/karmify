import { Plus } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Playlist } from "../types";
import { Swatch, hueOf } from "./primitives";

interface PlaylistMenuProps {
  playlists: Playlist[];
  /** genre_key of the resolver's guess, marked with ✦ in the list. */
  suggested?: string | null;
  onPick: (playlist: Playlist) => void;
  onCreate: (displayName: string) => void;
}

/**
 * The ⋯ button and its panel: pick any playlist, or create one that does not
 * exist yet. This is the only path to a new genre — the seeded five are a
 * starting point, not the whole world.
 */
export function PlaylistMenu({ playlists, suggested, onPick, onCreate }: PlaylistMenuProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  const PANEL_WIDTH = 230;
  const PANEL_MAX_HEIGHT = 260;

  // Fixed positioning, measured from the button: the table scrolls, so an
  // absolutely positioned panel would be clipped by it.
  useLayoutEffect(() => {
    if (!open || !button.current) return;
    const r = button.current.getBoundingClientRect();
    const below = window.innerHeight - r.bottom;
    const flip = below < PANEL_MAX_HEIGHT && r.top > below;
    setPos({
      top: flip ? Math.max(8, r.top - PANEL_MAX_HEIGHT - 6) : r.bottom + 6,
      left: Math.max(8, r.right - PANEL_WIDTH),
    });
    input.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      const target = e.target as Node;
      if (!panel.current?.contains(target) && !button.current?.contains(target)) close();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function close() {
    setOpen(false);
    setQuery("");
    setPos(null);
  }

  const needle = query.trim().toLowerCase();
  const matches = needle
    ? playlists.filter((p) => p.display_name.toLowerCase().includes(needle))
    : playlists;
  const exact = playlists.some((p) => p.display_name.toLowerCase() === needle);
  const canCreate = needle.length > 0 && !exact;

  function take(playlist: Playlist) {
    onPick(playlist);
    close();
  }

  function create() {
    onCreate(query.trim());
    close();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key !== "Enter") return;
    if (matches.length === 1) take(matches[0]);
    else if (canCreate) create();
  }

  return (
    <>
      <button
        ref={button}
        className={open ? "pick-menu open" : "pick-menu"}
        onClick={() => setOpen((v) => !v)}
        title="Все плейлисты — или создать новый"
      >
        ⋯
      </button>

      {open && pos && (
        <div className="pick-panel" ref={panel} style={{ top: pos.top, left: pos.left }}>
          <input
            ref={input}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Найди или создай…"
          />

          <div className="pick-panel-list">
            {matches.map((p) => (
              <button key={p.id} className="pick-panel-row" onClick={() => take(p)}>
                <Swatch hue={hueOf(p)} size={6} />
                <span className="name">{p.display_name}</span>
                {p.genre_key === suggested && (
                  <span style={{ color: hueOf(p), fontSize: 10 }}>✦</span>
                )}
              </button>
            ))}
            {matches.length === 0 && !canCreate && (
              <div className="pick-panel-empty">Ничего не совпало</div>
            )}
          </div>

          {canCreate && (
            <button className="pick-panel-create" onClick={create}>
              <Plus size={13} strokeWidth={1.75} />
              Создать «{query.trim()}»
            </button>
          )}
        </div>
      )}
    </>
  );
}
