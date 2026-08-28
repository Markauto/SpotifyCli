"""Add a track to the playback queue on an active device.

Spotify's docs are explicit that /me/player/queue "only works for users who have Spotify
Premium." Non-Premium accounts get a 403; if there's no actively playing device, Spotify
returns a 404 with reason NO_ACTIVE_DEVICE. Both are detected here and turned into a clear
message rather than a raw HTTP error, per the project's "no brittle workarounds" guidance —
there is no way to force playback to start on a device via this endpoint, so we just report
the situation clearly.

`queue` and `devices` are plain top-level commands (not a sub-group), matching the CLI shape
requested for this project.
"""

from __future__ import annotations

import typer

from ..api_client import build_client
from ..cli_support import cli_command
from ..errors import ApiError, ConfigError
from ..matching import pick_best_track
from ..models import Device, Track
from ..output import console, emit_json


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


@cli_command
async def queue_track(
    ctx: typer.Context,
    track: str = typer.Argument(..., help='Track title to search for, e.g. "Them Bones".'),
    artist: str | None = typer.Option(None, "--artist", help="Artist name, to disambiguate the track search."),
    track_uri: str | None = typer.Option(None, "--track-uri", help="Exact Spotify track URI/ID, bypassing search."),
    device_id: str | None = typer.Option(None, "--device-id", help="Target a specific device instead of the active one."),
) -> None:
    """Adds a track to the playback queue. Requires Spotify Premium and an active device
    (start playing something on a device first — Spotify does not let this API start
    playback on its own)."""
    json_mode = ctx.obj.json_mode
    async with build_client() as client:
        resolved = await _resolve_track(client, track, artist, track_uri)
        params = {"uri": resolved.uri}
        if device_id:
            params["device_id"] = device_id
        try:
            await client.post("/me/player/queue", params=params)
        except ApiError as e:
            if e.status_code == 404:
                raise ApiError(
                    "No active Spotify device found. Start playing something on a device "
                    "(phone, desktop, or web player) and try again — this API cannot start "
                    "playback itself."
                ) from e
            if e.status_code == 403:
                raise ApiError(
                    "Spotify refused this request (403) — adding to the queue requires "
                    "Spotify Premium."
                ) from e
            raise

    result = {"queued": True, "track": resolved.to_dict()}
    if json_mode:
        emit_json(result)
    else:
        console.print(f"Queued {resolved.label}.")


@cli_command
async def list_devices(ctx: typer.Context) -> None:
    """Lists available playback devices — useful to check before queueing a track."""
    json_mode = ctx.obj.json_mode
    async with build_client() as client:
        data = await client.get("/me/player/devices")
    devices = [Device.from_api(d) for d in data.get("devices", [])]

    if json_mode:
        emit_json({"devices": [d.to_dict() for d in devices]})
    elif not devices:
        console.print("No available devices. Open Spotify on a device to make it available.")
    else:
        from rich.table import Table

        table = Table(title="Devices", show_header=True, header_style="bold")
        table.add_column("Name")
        table.add_column("Type")
        table.add_column("Active")
        table.add_column("ID", style="dim")
        for d in devices:
            table.add_row(d.name, d.type, "yes" if d.is_active else "no", d.id or "")
        console.print(table)
