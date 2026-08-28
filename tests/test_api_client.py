import asyncio

import httpx
import pytest

from spotify_cli.api_client import SpotifyClient
from spotify_cli.config import Settings
from spotify_cli.errors import ApiError


async def _token_provider(force_refresh: bool = False) -> str:
    return "fake-token"


def make_client(handler) -> SpotifyClient:
    settings = Settings(client_id="x", redirect_uri="http://127.0.0.1:8888/callback")
    client = SpotifyClient(settings, _token_provider)
    client._http = httpx.AsyncClient(
        base_url=settings.api_base, transport=httpx.MockTransport(handler), timeout=5.0
    )
    return client


def test_paginate_follows_next():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "offset" not in str(request.url):
            return httpx.Response(
                200,
                json={"items": [{"n": 1}, {"n": 2}], "next": "https://api.spotify.com/v1/thing?offset=2"},
            )
        return httpx.Response(200, json={"items": [{"n": 3}], "next": None})

    async def run():
        client = make_client(handler)
        items = []
        async for item in client.paginate("/thing"):
            items.append(item)
        return items

    items = asyncio.run(run())
    assert [i["n"] for i in items] == [1, 2, 3]


def test_429_retries_then_succeeds(monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("spotify_cli.api_client.asyncio.sleep", fake_sleep)

    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": {"message": "rate limited"}})
        return httpx.Response(200, json={"ok": True})

    async def run():
        client = make_client(handler)
        return await client.get("/thing")

    result = asyncio.run(run())
    assert result == {"ok": True}
    assert attempts["n"] == 2
    assert sleeps == [2.0]


def test_error_response_raises_api_error_with_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"status": 404, "message": "Playlist not found"}})

    async def run():
        client = make_client(handler)
        await client.get("/playlists/doesnotexist")

    with pytest.raises(ApiError) as exc:
        asyncio.run(run())
    assert exc.value.status_code == 404
    assert "Playlist not found" in exc.value.message


def test_204_no_content_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    async def run():
        client = make_client(handler)
        return await client.post("/me/player/queue", params={"uri": "spotify:track:x"})

    assert asyncio.run(run()) is None
