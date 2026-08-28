"""Thin async Spotify Web API client: auth header injection, 401 refresh-and-retry,
429 rate-limit backoff (honouring Retry-After), and cursor pagination via the `next` field.

Endpoint choices here reflect the *current* (2025+) Spotify Web API surface, not older
tutorials you may see elsewhere:
  - Playlist items live at /playlists/{id}/items, not the deprecated .../tracks. The
    response objects were renamed to match: each page entry nests the track under "item"
    (not "track"), a playlist object carries its count at items.total (not tracks.total),
    and `fields` selectors must be written items(item(...)) accordingly. Reading the old
    keys silently yields empty results rather than an error, which in particular makes the
    duplicate check in `playlist add`/`import` pass everything through.
  - Removing playlist items takes {"items": [{"uri": ...}]}, not the old
    {"tracks": [...]} body, and there is no per-position removal any more — removal is
    purely by URI (see playlist.dedupe_plan for how this CLI works around that).
  - Do NOT send a snapshot_id with a removal. The read endpoints serve a stale one: after
    a playlist is mutated, GET /playlists/{id} and GET /me/playlists still report the
    pre-mutation snapshot_id (their item counts do update). Removing against that older
    version is accepted with a 200 and silently deletes the wrong occurrences, or none.
    Omitting the field removes against the playlist's current state, which is what every
    caller here wants.
  - Saved-track ("library") reads still use GET /me/tracks, which remains current.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx

from .config import Settings, load_settings, token_path
from .errors import ApiError

TokenProvider = Callable[..., Awaitable[str]]


class SpotifyClient:
    def __init__(self, settings: Settings, token_provider: TokenProvider, *, max_retries: int = 5):
        self._settings = settings
        self._token_provider = token_provider
        self._max_retries = max_retries
        self._http = httpx.AsyncClient(base_url=settings.api_base, timeout=settings.request_timeout)

    async def __aenter__(self) -> "SpotifyClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._http.aclose()

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_resp: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            force_refresh = attempt > 0 and last_resp is not None and last_resp.status_code == 401
            token = await self._token_provider(force_refresh=force_refresh)
            headers = dict(kwargs.pop("headers", None) or {})
            headers["Authorization"] = f"Bearer {token}"

            resp = await self._http.request(method, url, headers=headers, **kwargs)
            last_resp = resp

            if resp.status_code == 429 and attempt < self._max_retries:
                retry_after = float(resp.headers.get("Retry-After", "1") or "1")
                await asyncio.sleep(min(retry_after, 30.0))
                continue
            if resp.status_code == 401 and attempt < self._max_retries:
                # Access token may have expired between our freshness check and the
                # call itself; force one refresh and retry before giving up.
                continue
            return resp
        return last_resp  # pragma: no cover - loop always returns above

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.is_success:
            return
        message = resp.text
        try:
            body = resp.json()
            message = (body.get("error") or {}).get("message", message) if isinstance(body, dict) else message
        except ValueError:
            pass
        raise ApiError(message or f"Spotify API error ({resp.status_code})", status_code=resp.status_code, response_body=resp.text)

    async def request_json(self, method: str, url: str, **kwargs) -> Any:
        resp = await self._request(method, url, **kwargs)
        self._raise_for_status(resp)
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            # Some endpoints (e.g. POST /me/player/queue) return a 200 with a
            # non-JSON body (a bare opaque token) instead of 204. Treat it the
            # same as an empty body rather than crashing the caller.
            return None

    async def get(self, url: str, **kwargs) -> Any:
        return await self.request_json("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> Any:
        return await self.request_json("POST", url, **kwargs)

    async def put(self, url: str, **kwargs) -> Any:
        return await self.request_json("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs) -> Any:
        return await self.request_json("DELETE", url, **kwargs)

    async def paginate(self, path: str, *, params: dict | None = None, items_key: str = "items") -> AsyncIterator[dict]:
        """Yields every item across all pages, following the absolute `next` URL Spotify returns."""
        url: str | None = path
        use_params = params
        while url:
            resp = await self._request("GET", url, params=use_params)
            self._raise_for_status(resp)
            data = resp.json()
            for item in data.get(items_key, []) or []:
                yield item
            url = data.get("next")
            use_params = None  # `next` already carries the query string


def build_client(settings: Settings | None = None):
    """Returns a ready-to-use SpotifyClient as an async context manager."""
    from .auth import TokenStore  # local import to avoid a circular import at module load time

    settings = settings or load_settings()
    token_store = TokenStore(token_path(), settings)
    return SpotifyClient(settings, token_store.get_access_token)
