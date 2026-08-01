import { Download, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { PushToast } from "../components/Toast";
import { FormatBadge, humanDuration, humanSize } from "../components/primitives";
import type { SearchResult, SourceState } from "../types";

interface SearchViewProps {
  sources: SourceState[];
  push: PushToast;
}

const COLUMNS = "1fr 130px 100px 80px 44px";

export function SearchView({ sources, push }: SearchViewProps) {
  const [query, setQuery] = useState("");
  const [source, setSource] = useState<string | null>(null);
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState<Set<string>>(new Set());

  // Source health lives above this view. When the selected one goes down the
  // selection has to fall back to the best live source in the same render.
  useEffect(() => {
    const live = sources.filter((s) => s.up);
    const current = sources.find((s) => s.name === source);
    if (!current || !current.up) setSource(live[0]?.name ?? null);
  }, [sources, source]);

  const selected = sources.find((s) => s.name === source);

  async function go() {
    if (!query.trim() || !source) return;
    setBusy(true);
    try {
      setResults(await api.search(query, source));
    } catch (err) {
      push("error", `Поиск не удался: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  }

  async function download(result: SearchResult) {
    setDownloading((prev) => new Set(prev).add(result.download_ref));
    push("info", `Качаю: ${result.artist} — ${result.title}`);
    try {
      const r = await api.downloadResult(result);
      push("success", `Скачано: ${r.path.split(/[\\/]/).pop() ?? r.path}`);
    } catch (err) {
      push("error", `Не скачалось: ${String(err)}`);
    } finally {
      setDownloading((prev) => {
        const next = new Set(prev);
        next.delete(result.download_ref);
        return next;
      });
    }
  }

  return (
    <div className="view">
      <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: "22px 26px 0" }}>
        <div style={{ display: "flex", gap: 10 }}>
          <label className="field" style={{ flex: 1 }}>
            <Search size={15} strokeWidth={1.75} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && go()}
              placeholder="Артист, трек…"
            />
          </label>
          <button
            className="btn btn-accent btn-field"
            onClick={go}
            disabled={busy || !query.trim() || !source}
          >
            {busy ? "Ищу…" : "Найти"}
          </button>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="label-caps">Где искать</span>
          <div style={{ display: "flex", gap: 6 }}>
            {sources.map((s) => {
              const classes = ["source-pick"];
              if (s.name === source) classes.push("selected");
              if (!s.up) classes.push("down");
              return (
                <button
                  key={s.name}
                  className={classes.join(" ")}
                  disabled={!s.up}
                  onClick={() => setSource(s.name)}
                  title={s.up ? `Качество: ${s.quality}` : `${s.name} не отвечает`}
                >
                  <span className={s.up ? "dot up" : "dot down"} />
                  <span className="name">{s.name}</span>
                  <span className="quality">{s.up ? s.quality : "не отвечает"}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {results === null ? (
        <div className="empty">
          <h3>Ручной поиск по источникам</h3>
          <p>
            Для трека, которого нет в лайках, или когда автоскачивание нашло не тот файл. Soulseek
            отдаёт lossless — он первый в списке.
          </p>
        </div>
      ) : results.length === 0 ? (
        <div className="empty">
          <h3>
            {selected && !selected.up
              ? `${selected.name} не отвечает`
              : `Ничего не нашлось в ${source}`}
          </h3>
          <p>
            {selected && !selected.up
              ? "Выбери другой источник — lossless остался в bandcamp."
              : "Попробуй короче: только артист или только название, без ремиксов и скобок."}
          </p>
        </div>
      ) : (
        <div style={{ marginTop: 16 }}>
          <div className="thead" style={{ gridTemplateColumns: COLUMNS }}>
            <span className="label-caps">Трек</span>
            <span className="label-caps">Качество</span>
            <span className="label-caps">Размер</span>
            <span className="label-caps">Длина</span>
            <span />
          </div>

          {results.map((r, i) => (
            <div
              key={`${r.download_ref}-${i}`}
              className="trow compact"
              style={{ gridTemplateColumns: COLUMNS }}
            >
              <div className="title-cell">
                <span className="artist">{r.artist}</span>
                <span className="track">{r.title}</span>
              </div>
              <span>
                {r.audio_format ? (
                  <FormatBadge format={r.audio_format} bitrate={r.bitrate} />
                ) : (
                  <span className="dim">?</span>
                )}
              </span>
              <span className="meta-cell num">{humanSize(r.size_bytes)}</span>
              <span className="meta-cell num">{humanDuration(r.duration_sec)}</span>
              <button
                className="icon-btn"
                disabled={downloading.has(r.download_ref)}
                onClick={() => download(r)}
                title="Скачать"
              >
                <Download size={12} strokeWidth={1.75} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
