"""Default genre playlists and mapper aliases for the AUX MASTERS crew.

Seeded once through ``POST /playlists/init`` (idempotent — extending these
tuples and re-running only adds what is missing). Aliases are what the genre
mapper resolves incoming genre strings against; each genre lists its own key
too, so an exact hit like "acid" maps without a special case.
"""

from __future__ import annotations

#: (genre_key, display name / Spotify playlist name, button emoji)
DEFAULT_PLAYLISTS: tuple[tuple[str, str, str], ...] = (
    ("hardgroove", "Hardgroove", "🔊"),
    ("rave", "Rave Techno", "⚡"),
    ("electro", "Electro", "🔌"),
    ("acid", "Acid", "🧪"),
    ("jungle", "Jungle", "🌴"),
)

DEFAULT_ALIASES: dict[str, tuple[str, ...]] = {
    "hardgroove": (
        "hardgroove",
        "hard groove",
        "dark techno",
        "industrial techno",
        "peak time techno",
    ),
    "rave": ("rave", "rave techno", "hard techno", "schranz"),
    "electro": ("electro", "new electro", "electro house", "miami bass"),
    "acid": ("acid", "acid techno", "acid house", "303"),
    "jungle": ("jungle", "ragga jungle", "breakbeat", "drum and bass", "dnb"),
}
