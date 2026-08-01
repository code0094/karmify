export interface Track {
  id: number;
  spotify_track_id: string;
  track_name: string | null;
  artist_name: string | null;
  liked_by: string;
  detected_genre: string | null;
  genre_source: string | null;
  record_label: string | null;
  assigned_playlist_id: string | null;
  downloaded_at: string | null;
  download_path: string | null;
  /** Which source delivered the file — shown in the library's Файл column. */
  download_source: string | null;
  download_started_at: string | null;
  last_download_error: string | null;
}

export interface Playlist {
  id: number;
  genre_key: string;
  playlist_id: string;
  display_name: string;
  emoji: string;
  hue: string | null;
  total_tracks: number;
  downloaded: number;
  downloading: number;
  failed: number;
}

export interface SearchResult {
  source: string;
  title: string;
  artist: string;
  download_ref: string;
  audio_format?: string | null;
  bitrate?: number | null;
  size_bytes?: number | null;
  duration_sec?: number | null;
  extra?: Record<string, unknown>;
}

export interface CrewMember {
  label: string;
  display_name: string;
  spotify_connected: boolean;
  owner: boolean;
}

export interface Crew {
  name: string | null;
  members: CrewMember[];
}

/** One music source's availability, from GET /health. */
export interface SourceState {
  name: string;
  up: boolean;
  /** What it delivers, in the user's words: "flac и выше", "mp3 320". */
  quality: string;
}

export interface TrackFilters {
  genre?: string;
  liked_by?: string;
  only_undownloaded?: boolean;
}
