"""Parsing for `spotify playlist import`'s track list files. Pure, network-free, and kept
separate from the command so it can be unit tested directly.

Supported formats:
  - Plain text (default, or any non-.json file / stdin that doesn't look like a JSON array):
    one track per line. "#" starts a comment; blank lines are ignored. A line may be:
      Track Title
      Track Title | Artist
      spotify:track:<id>                         (used directly, no search)
      https://open.spotify.com/track/<id>...      (used directly, no search)
  - JSON (a file named *.json, or stdin content starting with '['): a top-level array whose
    items are either a plain string (track title) or an object with "track"/"title",
    optional "artist", or "uri" for a direct Spotify track URI/URL.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError


@dataclass
class TrackEntry:
    raw: str
    query: str | None
    artist: str | None
    uri: str | None


def _uri_from_url_or_uri(value: str) -> str:
    value = value.strip()
    if value.startswith("spotify:track:"):
        return value
    if "open.spotify.com/track/" in value:
        track_id = value.rsplit("/track/", 1)[-1].split("?")[0]
        return f"spotify:track:{track_id}"
    return value


def parse_text_track_list(text: str) -> list[TrackEntry]:
    entries: list[TrackEntry] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("spotify:track:") or "open.spotify.com/track/" in line:
            entries.append(TrackEntry(raw=line, query=None, artist=None, uri=_uri_from_url_or_uri(line)))
            continue
        if "|" in line:
            title, artist = line.split("|", 1)
            title = title.strip()
            artist = artist.strip() or None
            if not title:
                raise ConfigError(f"Empty track title in line: '{raw_line}'")
            entries.append(TrackEntry(raw=line, query=title, artist=artist, uri=None))
        else:
            entries.append(TrackEntry(raw=line, query=line, artist=None, uri=None))
    return entries


def parse_json_track_list(text: str) -> list[TrackEntry]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON track list: {e}") from e
    if not isinstance(data, list):
        raise ConfigError("JSON track list must be a top-level array.")

    entries: list[TrackEntry] = []
    for i, item in enumerate(data):
        if isinstance(item, str):
            entries.append(TrackEntry(raw=item, query=item, artist=None, uri=None))
            continue
        if not isinstance(item, dict):
            raise ConfigError(f"JSON track list item #{i} must be a string or an object.")

        uri = item.get("uri")
        title = item.get("track") or item.get("title")
        artist = item.get("artist")
        if not uri and not title:
            raise ConfigError(f"JSON track list item #{i} needs a 'track'/'title' field or a 'uri' field.")

        raw = uri or title or f"item #{i}"
        entries.append(
            TrackEntry(raw=raw, query=title, artist=artist, uri=_uri_from_url_or_uri(uri) if uri else None)
        )
    return entries


def parse_track_list(text: str, *, looks_like_json: bool) -> list[TrackEntry]:
    if looks_like_json:
        return parse_json_track_list(text)
    return parse_text_track_list(text)


def load_track_list_file(path: str) -> list[TrackEntry]:
    """Loads and parses a track list from a file path, or from stdin if path is '-'."""
    if path == "-":
        text = sys.stdin.read()
        looks_like_json = text.lstrip().startswith("[")
    else:
        file_path = Path(path)
        if not file_path.exists():
            raise ConfigError(f"Track list file not found: {path}")
        text = file_path.read_text(encoding="utf-8")
        looks_like_json = file_path.suffix.lower() == ".json"

    entries = parse_track_list(text, looks_like_json=looks_like_json)
    if not entries:
        raise ConfigError(f"No track entries found in {path!r}.")
    return entries
