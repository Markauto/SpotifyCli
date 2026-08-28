"""Your Liked Songs (Spotify's "library" of saved tracks).

Uses the classic GET/PUT/DELETE /me/tracks endpoints. Spotify's current OpenAPI spec marks
PUT/DELETE /me/tracks and GET /me/tracks/contains as deprecated in favor of a newer, generic
/me/library and /me/library/contains (which also cover albums/shows/episodes in one call) —
but the classic track-only endpoints are still live and far more battle-tested. If Spotify
ever removes them, this is the one place to update.
"""

from __future__ import annotations

import typer

from ..api_client import build_client
from ..cli_support import cli_command
from ..errors import ConfigError
from ..matching import pick_best_track
from ..models import Track
from ..output import console, emit_json, render_tracks_table

library_app = typer.Typer(help="Manage your Liked Songs (saved tracks library).")


async def _resolve_track(client, query: str | None, artist: str | None, track_uri: str | None) -> Track:
    if track_uri:
        track_id = track_uri.rsplit(":", 1)[-1]
        data = await client.get(f"/tracks/{track_id}")
        return Track.from_api(data)
    if not query:
        raise ConfigError("Provide a track name or --track-uri.")
    q = f'track:"{query}" artist:"{artist}"' if artist else query
    data = await client.get("/search", params={"q": q, "type": "track", "limit": 20})
    candidates = [Track.from_api(t) for t in (data.get("tracks") or {}).get("items", [])]
    return pick_best_track(candidates, query, artist)


@library_app.command("list")
@cli_command
async def library_list(
    ctx: typer.Context,
    limit: int = typer.Option(50, "--limit", min=1, max=2000, help="Max tracks to display."),
) -> None:
    """Lists tracks saved to your library (Liked Songs), most recently added first."""
    json_mode = ctx.obj.json_mode
    tracks: list[Track] = []
    async with build_client() as client:
        async for item in client.paginate("/me/tracks", params={"limit": 50}):
            t = item.get("track")
            if t and t.get("id"):
                tracks.append(Track.from_api(t))
            if len(tracks) >= limit:
                break

    if json_mode:
        emit_json({"tracks": [t.to_dict() for t in tracks]})
    elif not tracks:
        console.print("Your library has no saved tracks.")
    else:
        render_tracks_table(tracks, title="Liked Songs")


@library_app.command("add")
@cli_command
async def library_add(
    ctx: typer.Context,
    track: str = typer.Argument(..., help='Track title to search for, e.g. "Would?".'),
    artist: str | None = typer.Option(None, "--artist", help="Artist name, to disambiguate the track search."),
    track_uri: str | None = typer.Option(None, "--track-uri", help="Exact Spotify track URI/ID, bypassing search."),
) -> None:
    """Saves a track to your library (Liked Songs)."""
    json_mode = ctx.obj.json_mode
    async with build_client() as client:
        resolved = await _resolve_track(client, track, artist, track_uri)
        already = await client.get("/me/tracks/contains", params={"ids": resolved.id})
        if already and already[0]:
            result = {"added": False, "reason": "already_saved", "track": resolved.to_dict()}
            if json_mode:
                emit_json(result)
            else:
                console.print(f"{resolved.label} is already in your library.")
            return
        await client.put("/me/tracks", params={"ids": resolved.id})

    result = {"added": True, "track": resolved.to_dict()}
    if json_mode:
        emit_json(result)
    else:
        console.print(f"Added {resolved.label} to your library.")


@library_app.command("remove")
@cli_command
async def library_remove(
    ctx: typer.Context,
    track: str = typer.Argument(..., help='Track title to search for, e.g. "Would?".'),
    artist: str | None = typer.Option(None, "--artist", help="Artist name, to disambiguate the track search."),
    track_uri: str | None = typer.Option(None, "--track-uri", help="Exact Spotify track URI/ID, bypassing search."),
) -> None:
    """Removes a track from your library (Liked Songs)."""
    json_mode = ctx.obj.json_mode
    async with build_client() as client:
        resolved = await _resolve_track(client, track, artist, track_uri)
        already = await client.get("/me/tracks/contains", params={"ids": resolved.id})
        if not (already and already[0]):
            result = {"removed": False, "reason": "not_saved", "track": resolved.to_dict()}
            if json_mode:
                emit_json(result)
            else:
                console.print(f"{resolved.label} is not in your library.")
            return
        await client.delete("/me/tracks", params={"ids": resolved.id})

    result = {"removed": True, "track": resolved.to_dict()}
    if json_mode:
        emit_json(result)
    else:
        console.print(f"Removed {resolved.label} from your library.")
