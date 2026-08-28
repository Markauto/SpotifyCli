"""Regression tests for the /playlists/{id}/items request and response shapes.

Two API details here fail silently rather than loudly, so they need pinning:

  - The endpoint nests each track under "item" (not "track") and reports a playlist's count
    at items.total (not tracks.total). Reading the old keys yields nothing instead of
    raising, which silently disabled the duplicate check in `playlist add`/`import`.
  - A removal must not carry a snapshot_id, because the read endpoints serve a stale one.
    Removing against that older version is accepted with a 200 and removes the wrong
    occurrences, or none.
"""

import asyncio
import json

import httpx

from spotify_cli.api_client import SpotifyClient
from spotify_cli.commands.playlist import (
    _get_playlist_tracks,
    _iter_playlist_track_uris,
    _remove_all_occurrences,
)
from spotify_cli.config import Settings
from spotify_cli.models import Playlist


async def _token_provider(force_refresh: bool = False) -> str:
    return "fake-token"


def make_client(handler) -> SpotifyClient:
    settings = Settings(client_id="x", redirect_uri="http://127.0.0.1:8888/callback")
    client = SpotifyClient(settings, _token_provider)
    client._http = httpx.AsyncClient(
        base_url=settings.api_base, transport=httpx.MockTransport(handler), timeout=5.0
    )
    return client


def _items_page(*tracks) -> dict:
    return {"items": [{"added_at": "2025-01-01T00:00:00Z", "item": t} for t in tracks], "next": None}


ROADS = {
    "id": "2sW8fmnISifQTRgnRrQTYW",
    "uri": "spotify:track:2sW8fmnISifQTRgnRrQTYW",
    "name": "Roads",
    "duration_ms": 303973,
    "artists": [{"name": "Portishead"}],
    "album": {"name": "Dummy"},
}


def test_get_playlist_tracks_reads_the_item_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_items_page(ROADS))

    async def run():
        return await _get_playlist_tracks(make_client(handler), "playlist123")

    tracks = asyncio.run(run())
    assert [t.name for t in tracks] == ["Roads"]
    assert tracks[0].artists == ["Portishead"]


def test_iter_playlist_track_uris_reads_the_item_key():
    """This is the duplicate-check path — yielding nothing means every add is a double-add."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_items_page(ROADS))

    async def run():
        return [uri async for uri in _iter_playlist_track_uris(make_client(handler), "playlist123")]

    assert asyncio.run(run()) == ["spotify:track:2sW8fmnISifQTRgnRrQTYW"]


def test_playlist_fields_selector_requests_the_item_key():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("fields"))
        return httpx.Response(200, json={"items": [], "next": None})

    async def run():
        await _get_playlist_tracks(make_client(handler), "playlist123")

    asyncio.run(run())
    assert seen == ["items(item(id,uri,name,duration_ms,artists(name),album(name))),next"]


def test_removal_sends_no_snapshot_id():
    """A stale snapshot_id makes Spotify remove against an older version of the playlist —
    accepted with a 200, wrong (or no) items gone. Omitting it targets the current state."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"snapshot_id": "new-snap"})

    async def run():
        await _remove_all_occurrences(make_client(handler), "playlist123", ROADS["uri"])

    asyncio.run(run())
    assert seen["method"] == "DELETE"
    assert seen["url"].endswith("/playlists/playlist123/items")
    assert seen["body"] == {"items": [{"uri": ROADS["uri"]}]}
    assert "snapshot_id" not in seen["body"]


def test_playlist_total_tracks_reads_items_total():
    playlist = Playlist.from_api(
        {
            "id": "playlist123",
            "name": "Neon Grief",
            "owner": {"id": "someone"},
            "public": False,
            "collaborative": False,
            "snapshot_id": "snap",
            "items": {"total": 26},
        }
    )
    assert playlist.total_tracks == 26
