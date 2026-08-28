"""Turning a user-supplied name into a concrete Spotify item: shared by every command that
resolves a track, album, or playlist by search/name (playlist add/remove/add-album/import,
library add/remove, queue). Centralized here so all of them behave identically, including
the optional interactive disambiguation prompt.
"""

from __future__ import annotations

import sys
from difflib import SequenceMatcher

from .api_client import SpotifyClient
from .errors import AmbiguousMatchError, ConfigError, NotFoundError, SpotifyCliError
from .matching import pick_best_track, resolve_playlist
from .models import Playlist, Track
from .output import prompt_pick_candidate


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


async def resolve_track(
    client: SpotifyClient,
    query: str | None,
    artist: str | None,
    track_uri: str | None,
    *,
    interactive: bool = False,
) -> Track:
    if track_uri:
        track_id = track_uri.rsplit(":", 1)[-1]
        data = await client.get(f"/tracks/{track_id}")
        return Track.from_api(data)
    if not query:
        raise ConfigError("Provide a track name or --track-uri.")

    q = f'track:"{query}" artist:"{artist}"' if artist else query
    data = await client.get("/search", params={"q": q, "type": "track", "limit": 10})
    candidates = [Track.from_api(t) for t in (data.get("tracks") or {}).get("items", [])]

    try:
        return pick_best_track(candidates, query, artist)
    except AmbiguousMatchError as exc:
        if interactive and sys.stdin.isatty():
            chosen = prompt_pick_candidate(exc.candidates, noun="track")
            if chosen is None:
                raise SpotifyCliError(f"Cancelled — no track selected for '{query}'.") from exc
            chosen_uri = exc.candidates[chosen]["uri"]
            return next(t for t in candidates if t.uri == chosen_uri)
        raise


async def resolve_album(
    client: SpotifyClient,
    query: str | None,
    artist: str | None,
    album_uri: str | None,
    *,
    interactive: bool = False,
) -> dict:
    if album_uri:
        album_id = album_uri.rsplit(":", 1)[-1]
        return await client.get(f"/albums/{album_id}")
    if not query:
        raise ConfigError("Provide an album name or --album-uri.")

    q = f'album:"{query}"' + (f' artist:"{artist}"' if artist else "")
    data = await client.get("/search", params={"q": q, "type": "album", "limit": 10})
    items = (data.get("albums") or {}).get("items", [])
    if not items:
        suffix = f" by '{artist}'" if artist else ""
        raise NotFoundError(f"No album found matching '{query}'{suffix}.")

    scored = sorted(items, key=lambda a: _name_similarity(a["name"], query), reverse=True)
    best_score = _name_similarity(scored[0]["name"], query)
    second_score = _name_similarity(scored[1]["name"], query) if len(scored) > 1 else 0.0

    if best_score >= 0.92 and best_score - second_score >= 0.08:
        return await client.get(f"/albums/{scored[0]['id']}")

    candidates = [
        {"name": a["name"], "artists": [ar["name"] for ar in a.get("artists", [])], "uri": a["uri"], "id": a["id"]}
        for a in scored[:8]
    ]
    if interactive and sys.stdin.isatty():
        chosen = prompt_pick_candidate(candidates, noun="album")
        if chosen is None:
            raise SpotifyCliError(f"Cancelled — no album selected for '{query}'.")
        return await client.get(f"/albums/{candidates[chosen]['id']}")

    raise AmbiguousMatchError(
        f"Multiple albums match '{query}'. Pass --artist to narrow it down, --album-uri, or --interactive.",
        candidates=candidates,
    )


async def resolve_playlist_arg(
    client: SpotifyClient,
    all_playlists_fn,
    name: str,
    explicit_id: str | None,
    *,
    interactive: bool = False,
) -> Playlist:
    """`all_playlists_fn` is an async callable returning list[Playlist] — injected rather than
    imported directly to avoid a circular import with commands/playlist.py."""
    if explicit_id:
        data = await client.get(
            f"/playlists/{explicit_id}",
            params={"fields": "id,uri,name,owner,public,collaborative,snapshot_id,tracks(total)"},
        )
        return Playlist.from_api(data)

    playlists = await all_playlists_fn(client)
    try:
        return resolve_playlist(playlists, name)
    except AmbiguousMatchError as exc:
        if interactive and sys.stdin.isatty():
            chosen = prompt_pick_candidate(exc.candidates, noun="playlist")
            if chosen is None:
                raise SpotifyCliError(f"Cancelled — no playlist selected for '{name}'.") from exc
            chosen_id = exc.candidates[chosen]["id"]
            return next(p for p in playlists if p.id == chosen_id)
        raise
