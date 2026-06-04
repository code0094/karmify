import { useState } from "react";
import { api } from "../api";
import type { SearchResult } from "../types";

interface SearchBarProps {
  sources: string[];
  onResults: (results: SearchResult[]) => void;
}

export function SearchBar({ sources, onResults }: SearchBarProps) {
  const [query, setQuery] = useState("");
  const [source, setSource] = useState(sources[0] ?? "spotify");
  const [busy, setBusy] = useState(false);

  async function go() {
    if (!query.trim()) return;
    setBusy(true);
    try {
      onResults(await api.search(query, source));
    } catch (err) {
      alert(`Поиск не удался: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "flex", gap: 8, padding: 12 }}>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && go()}
        placeholder="Поиск трека…"
        style={{ flex: 1, padding: 6 }}
      />
      <select value={source} onChange={(e) => setSource(e.target.value)}>
        {sources.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <button onClick={go} disabled={busy}>
        {busy ? "Ищу…" : "Найти"}
      </button>
    </div>
  );
}
