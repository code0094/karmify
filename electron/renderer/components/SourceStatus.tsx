import { Radio, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { SourceState } from "../types";

interface SourceStatusProps {
  sources: SourceState[];
}

/**
 * Header pill showing how many sources are alive.
 *
 * Exists because a dead slskd is invisible otherwise: every download quietly
 * falls through to mp3 320 and nobody finds out until the gig.
 */
export function SourceStatus({ sources }: SourceStatusProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const up = sources.filter((s) => s.up).length;
  const degraded = sources.length > 0 && up < sources.length;

  return (
    <div className="source-status" ref={root}>
      <button
        className={degraded ? "source-pill degraded" : "source-pill"}
        onClick={() => setOpen((v) => !v)}
        title="Состояние источников скачивания"
      >
        {degraded ? <TriangleAlert size={13} strokeWidth={1.75} /> : <Radio size={13} strokeWidth={1.75} />}
        Источники
        <span className="num">
          {up}/{sources.length}
        </span>
      </button>

      {open && (
        <div className="source-popover">
          {sources.map((s) => (
            <div key={s.name} className={s.up ? "source-popover-row" : "source-popover-row down"}>
              <span className={s.up ? "dot up" : "dot down"} />
              <span className="name">{s.name}</span>
              <span className="dim" style={{ fontSize: 12 }}>
                {s.up ? s.quality : "не отвечает"}
              </span>
            </div>
          ))}
          <div className="source-popover-foot">
            {degraded
              ? "Пока источник лежит, скачивание падает на следующий по качеству."
              : "Качаю в порядке качества: soulseek → bandcamp → spotify."}
          </div>
        </div>
      )}
    </div>
  );
}
