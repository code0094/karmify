import { useEffect, useState } from "react";
import { api } from "../api";
import type { PushToast } from "../components/Toast";
import type { SearchResult } from "../types";

interface SearchViewProps {
  sources: string[];
  push: PushToast;
}

// Lossless-capable sources first — same preference the backend downloads with.
const SOURCE_ORDER = ["soulseek", "bandcamp", "spotify"];

function orderSources(sources: string[]): string[] {
  const rank = (s: string) => {
    const i = SOURCE_ORDER.indexOf(s);
    return i === -1 ? SOURCE_ORDER.length : i;
  };
  return [...sources].sort((a, b) => rank(a) - rank(b));
}

const LOSSLESS = new Set(["flac", "wav", "aiff", "aif", "alac"]);

function QualityBadge({ result }: { result: SearchResult }) {
  const fmt = (result.audio_format ?? "").toLowerCase();
  if (!fmt) return <span className="dim">?</span>;
  return (
    <span className={LOSSLESS.has(fmt) ? "fmt fmt-lossless" : "fmt"}>
      {fmt}
      {result.bitrate ? ` ${result.bitrate}` : ""}
    </span>
  );
}

function mb(size: number | null | undefined): string {
  return size ? `${(size / 1048576).toFixed(1)} МБ` : "";
}

function mmss(sec: number | null | undefined): string {
  if (!sec) return "";
  const m = Math.floor(sec / 60);
  const s = String(Math.floor(sec % 60)).padStart(2, "0");
  return `${m}:${s}`;
}

export function SearchView({ sources, push }: SearchViewProps) {
  const ordered = orderSources(sources);
  const [query, setQuery] = useState("");
  const [source, setSource] = useState(ordered[0] ?? "");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState<Set<string>>(new Set());

  // Sources arrive async from /health — pick the best one once they do.
  useEffect(() => {
    if (!source && ordered.length > 0) setSource(ordered[0]);
  }, [ordered, source]);

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
      const name = r.path.split(/[\\/]/).pop() ?? r.path;
      push("success", `Скачано: ${name}`);
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
    <div>
      <div className="library-toolbar">
        <input
          type="text"
          style={{ flex: 1 }}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && go()}
          placeholder="Артист, трек…"
        />
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          {ordered.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <button className="btn btn-accent" onClick={go} disabled={busy || !query.trim()}>
          {busy ? "Ищу…" : "Найти"}
        </button>
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
          <h3>Ничего не нашлось</h3>
          <p>Попробуй короче: только артист или только название, без ремиксов и скобок.</p>
        </div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Трек</th>
              <th>Качество</th>
              <th>Размер</th>
              <th>Длина</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {results.map((r, i) => (
              <tr key={`${r.download_ref}-${i}`}>
                <td>
                  <strong>{r.artist}</strong> — {r.title}
                  <span className="dim"> · {r.source}</span>
                </td>
                <td>
                  <QualityBadge result={r} />
                </td>
                <td className="dim">{mb(r.size_bytes)}</td>
                <td className="dim">{mmss(r.duration_sec)}</td>
                <td>
                  <button
                    className="btn"
                    disabled={downloading.has(r.download_ref)}
                    onClick={() => download(r)}
                  >
                    {downloading.has(r.download_ref) ? "⏳" : "⬇"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
