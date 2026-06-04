"""Pluggable music sources (Spotify/zotify, Soulseek, Bandcamp).

Every source implements the same :class:`~src.sources.base.MusicSource` interface
so the sidecar can search across all of them and download from whichever the user
picks. This mirrors the waterfall pattern already used by the genre resolver.
"""
