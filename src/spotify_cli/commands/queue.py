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
from ..errors import ApiError
from ..models import Device, Track
from ..output import console, emit_json
from ..resolution import resolve_track


@cli_command
async def queue_track(
    ctx: typer.Context,
    track: str = typer.Argument(..., help='Track title to search for, e.g. "Them Bones".'),
    artist: str | None = typer.Option(None, "--artist", help="Artist name, to disambiguate the track search."),
    track_uri: str | None = typer.Option(None, "--track-uri", help="Exact Spotify track URI/ID, bypassing search."),
    device_id: str | None = typer.Option(None, "--device-id", help="Target a specific device instead of the active one."),
    interactive: bool = typer.Option(
        False, "--interactive", "-i", help="If the track is ambiguous, prompt to choose instead of failing."
    ),
) -> None:
    """Adds a track to the playback queue. Requires Spotify Premium and an active device
    (start playing something on a device first — Spotify does not let this API start
    playback on its own)."""
    json_mode = ctx.obj.json_mode
    effective_interactive = interactive and not json_mode
    async with build_client() as client:
        resolved = await resolve_track(client, track, artist, track_uri, interactive=effective_interactive)
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


def _format_ms(ms: int | None) -> str:
    if ms is None:
        return "?"
    total_seconds = ms // 1000
    return f"{total_seconds // 60}:{total_seconds % 60:02d}"


@cli_command
async def now_playing(ctx: typer.Context) -> None:
    """Shows what's currently playing (or paused) on the account's active device."""
    json_mode = ctx.obj.json_mode
    async with build_client() as client:
        data = await client.get("/me/player/currently-playing")

    if not data or not data.get("item"):
        if json_mode:
            emit_json({"playing": False})
        else:
            console.print("Nothing is currently playing.")
        return

    content_type = data.get("currently_playing_type", "track")
    if content_type != "track":
        if json_mode:
            emit_json({"playing": True, "type": content_type, "track": None})
        else:
            console.print(f"Playing a {content_type}, not a track.")
        return

    track = Track.from_api(data["item"])
    is_playing = data.get("is_playing", False)
    progress_ms = data.get("progress_ms")
    device = (data.get("device") or {}).get("name")

    if json_mode:
        emit_json(
            {
                "playing": True,
                "is_playing": is_playing,
                "progress_ms": progress_ms,
                "duration_ms": track.duration_ms,
                "device": device,
                "track": track.to_dict(),
            }
        )
    else:
        state = "Playing" if is_playing else "Paused"
        progress = f"{_format_ms(progress_ms)}/{_format_ms(track.duration_ms)}"
        suffix = f" on {device}" if device else ""
        console.print(f"{state}: {track.label}  [{progress}]{suffix}")


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
