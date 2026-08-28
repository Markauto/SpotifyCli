from __future__ import annotations

from difflib import SequenceMatcher

import typer

from ..api_client import SpotifyClient, build_client
from ..cli_support import cli_command
from ..errors import AmbiguousMatchError, ConfigError, NotFoundError
from ..matching import dedupe_plan, pick_best_track, resolve_playlist
from ..models import Playlist, Track
from ..output import console, emit_json, render_playlists_table, render_tracks_table

playlist_app = typer.Typer(help="Manage playlists: list, show, create, add/remove tracks, add albums, dedupe.")


# --- internal helpers (shared by several commands below) -----------------------------

async def _get_all_playlists(client: SpotifyClient) -> list[Playlist]:
    playlists = []
    async for p in client.paginate("/me/playlists", params={"limit": 50}):
        playlists.append(Playlist.from_api(p))
    return playlists


async def _resolve_playlist_arg(client: SpotifyClient, name: str, explicit_id: str | None) -> Playlist:
    if explicit_id:
        data = await client.get(
            f"/playlists/{explicit_id}",
            params={"fields": "id,uri,name,owner,public,collaborative,snapshot_id,tracks(total)"},
        )
        return Playlist.from_api(data)
    playlists = await _get_all_playlists(client)
    return resolve_playlist(playlists, name)


async def _iter_playlist_track_uris(client: SpotifyClient, playlist_id: str):
    fields = "items(track(uri)),next"
    async for item in client.paginate(f"/playlists/{playlist_id}/items", params={"fields": fields}):
        track = item.get("track")
        if track and track.get("uri"):
            yield track["uri"]


async def _get_playlist_tracks(client: SpotifyClient, playlist_id: str) -> list[Track]:
    fields = "items(track(id,uri,name,duration_ms,artists(name),album(name))),next"
    tracks: list[Track] = []
    async for item in client.paginate(f"/playlists/{playlist_id}/items", params={"fields": fields}):
        t = item.get("track")
        if t and t.get("id"):
            tracks.append(Track.from_api(t))
    return tracks


async def _resolve_track(
    client: SpotifyClient, query: str | None, artist: str | None, track_uri: str | None
) -> Track:
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


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


async def _resolve_album(
    client: SpotifyClient, query: str | None, artist: str | None, album_uri: str | None
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

    raise AmbiguousMatchError(
        f"Multiple albums match '{query}'. Pass --artist to narrow it down, or --album-uri with an exact Spotify album URI.",
        candidates=[
            {"name": a["name"], "artists": [ar["name"] for ar in a.get("artists", [])], "uri": a["uri"], "id": a["id"]}
            for a in scored[:8]
        ],
    )


async def _get_album_tracks(client: SpotifyClient, album_id: str) -> list[Track]:
    tracks: list[Track] = []
    async for t in client.paginate(f"/albums/{album_id}/tracks"):
        tracks.append(Track.from_api(t))
    return tracks


def _visibility(p: Playlist) -> str:
    return "collaborative" if p.collaborative else ("public" if p.public else "private")


# --- commands --------------------------------------------------------------------------

@playlist_app.command("list")
@cli_command
async def playlist_list(ctx: typer.Context) -> None:
    """Lists all of your playlists (owned and followed)."""
    json_mode = ctx.obj.json_mode
    async with build_client() as client:
        playlists = await _get_all_playlists(client)

    if json_mode:
        emit_json({"playlists": [p.to_dict() for p in playlists]})
    elif not playlists:
        console.print("No playlists found.")
    else:
        render_playlists_table(playlists)


@playlist_app.command("show")
@cli_command
async def playlist_show(
    ctx: typer.Context,
    playlist: str = typer.Argument(..., help='Playlist name, e.g. "Driving".'),
    playlist_id: str | None = typer.Option(None, "--playlist-id", help="Exact Spotify playlist ID, bypassing name lookup."),
) -> None:
    """Shows a playlist's tracks."""
    json_mode = ctx.obj.json_mode
    async with build_client() as client:
        target = await _resolve_playlist_arg(client, playlist, playlist_id)
        tracks = await _get_playlist_tracks(client, target.id)

    if json_mode:
        emit_json({"playlist": target.to_dict(), "tracks": [t.to_dict() for t in tracks]})
    else:
        console.print(f"[bold]{target.name}[/bold] — {target.owner} — {len(tracks)} track(s) — {_visibility(target)}")
        render_tracks_table(tracks, title=target.name)


@playlist_app.command("create")
@cli_command
async def playlist_create(
    ctx: typer.Context,
    name: str = typer.Argument(..., help='Name for the new playlist, e.g. "90s Alt Rock".'),
    description: str = typer.Option("", "--description", help="Optional playlist description."),
    public: bool = typer.Option(True, "--public/--private", help="Whether the playlist is public."),
) -> None:
    """Creates a new playlist."""
    json_mode = ctx.obj.json_mode
    body: dict = {"name": name, "public": public}
    if description:
        body["description"] = description

    async with build_client() as client:
        data = await client.post("/me/playlists", json=body)
    playlist = Playlist.from_api(data)

    if json_mode:
        emit_json({"created": True, "playlist": playlist.to_dict()})
    else:
        console.print(f'Created playlist "{playlist.name}" ({_visibility(playlist)}) — {playlist.id}')


@playlist_app.command("add")
@cli_command
async def playlist_add(
    ctx: typer.Context,
    track: str = typer.Argument(..., help='Track title to search for, e.g. "Black Hole Sun".'),
    playlist: str = typer.Argument(..., help='Destination playlist name, e.g. "Driving".'),
    artist: str | None = typer.Option(None, "--artist", help="Artist name, to disambiguate the track search."),
    track_uri: str | None = typer.Option(None, "--track-uri", help="Exact Spotify track URI/ID, bypassing search."),
    playlist_id: str | None = typer.Option(None, "--playlist-id", help="Exact Spotify playlist ID, bypassing name lookup."),
    allow_duplicate: bool = typer.Option(False, "--allow-duplicate", help="Add even if the track is already in the playlist."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without making changes."),
) -> None:
    """Adds one track to a playlist, skipping it if already present (unless --allow-duplicate)."""
    json_mode = ctx.obj.json_mode
    async with build_client() as client:
        resolved_track = await _resolve_track(client, track, artist, track_uri)
        target_playlist = await _resolve_playlist_arg(client, playlist, playlist_id)
        existing_uris = {u async for u in _iter_playlist_track_uris(client, target_playlist.id)}
        already_present = resolved_track.uri in existing_uris

        if already_present and not allow_duplicate:
            result = {"added": False, "reason": "duplicate", "track": resolved_track.to_dict(), "playlist": target_playlist.to_dict()}
            if json_mode:
                emit_json(result)
            else:
                console.print(f'{resolved_track.label} is already in "{target_playlist.name}" — skipped (use --allow-duplicate to add anyway).')
            return

        if dry_run:
            result = {"added": False, "reason": "dry-run", "track": resolved_track.to_dict(), "playlist": target_playlist.to_dict()}
            if json_mode:
                emit_json(result)
            else:
                console.print(f'[dry-run] Would add {resolved_track.label} to "{target_playlist.name}".')
            return

        await client.post(f"/playlists/{target_playlist.id}/items", json={"uris": [resolved_track.uri]})

    result = {"added": True, "track": resolved_track.to_dict(), "playlist": target_playlist.to_dict()}
    if json_mode:
        emit_json(result)
    else:
        console.print(f'Added {resolved_track.label} to "{target_playlist.name}".')


@playlist_app.command("remove")
@cli_command
async def playlist_remove(
    ctx: typer.Context,
    track: str = typer.Argument(..., help='Track title to search for, e.g. "Black Hole Sun".'),
    playlist: str = typer.Argument(..., help='Playlist name to remove it from, e.g. "Driving".'),
    artist: str | None = typer.Option(None, "--artist", help="Artist name, to disambiguate the track search."),
    track_uri: str | None = typer.Option(None, "--track-uri", help="Exact Spotify track URI/ID, bypassing search."),
    playlist_id: str | None = typer.Option(None, "--playlist-id", help="Exact Spotify playlist ID, bypassing name lookup."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without making changes."),
) -> None:
    """Removes a track from a playlist. Spotify's API removes every occurrence of the
    matched track URI, so if a track appears multiple times, all copies are removed."""
    json_mode = ctx.obj.json_mode
    async with build_client() as client:
        resolved_track = await _resolve_track(client, track, artist, track_uri)
        target_playlist = await _resolve_playlist_arg(client, playlist, playlist_id)
        existing_uris = [u async for u in _iter_playlist_track_uris(client, target_playlist.id)]
        occurrences = existing_uris.count(resolved_track.uri)

        if occurrences == 0:
            result = {"removed": False, "reason": "not_present", "track": resolved_track.to_dict(), "playlist": target_playlist.to_dict()}
            if json_mode:
                emit_json(result)
            else:
                console.print(f'{resolved_track.label} is not in "{target_playlist.name}" — nothing to remove.')
            return

        if dry_run:
            result = {
                "removed": False,
                "reason": "dry-run",
                "occurrences": occurrences,
                "track": resolved_track.to_dict(),
                "playlist": target_playlist.to_dict(),
            }
            if json_mode:
                emit_json(result)
            else:
                console.print(f'[dry-run] Would remove {occurrences} occurrence(s) of {resolved_track.label} from "{target_playlist.name}".')
            return

        await client.delete(f"/playlists/{target_playlist.id}/items", json={"items": [{"uri": resolved_track.uri}]})

    result = {"removed": True, "occurrences": occurrences, "track": resolved_track.to_dict(), "playlist": target_playlist.to_dict()}
    if json_mode:
        emit_json(result)
    else:
        console.print(f'Removed {resolved_track.label} from "{target_playlist.name}".')


@playlist_app.command("add-album")
@cli_command
async def playlist_add_album(
    ctx: typer.Context,
    album: str = typer.Argument(..., help='Album title to search for, e.g. "Dirt".'),
    playlist: str = typer.Argument(..., help='Destination playlist name, e.g. "Grunge".'),
    artist: str | None = typer.Option(None, "--artist", help="Artist name, to disambiguate the album search."),
    album_uri: str | None = typer.Option(None, "--album-uri", help="Exact Spotify album URI/ID, bypassing search."),
    playlist_id: str | None = typer.Option(None, "--playlist-id", help="Exact Spotify playlist ID, bypassing name lookup."),
    allow_duplicate: bool = typer.Option(False, "--allow-duplicate", help="Add tracks even if already present."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without making changes."),
) -> None:
    """Adds every track of an album to a playlist, skipping tracks already present (unless --allow-duplicate)."""
    json_mode = ctx.obj.json_mode
    async with build_client() as client:
        album_obj = await _resolve_album(client, album, artist, album_uri)
        album_tracks = await _get_album_tracks(client, album_obj["id"])
        target_playlist = await _resolve_playlist_arg(client, playlist, playlist_id)
        existing_uris = {u async for u in _iter_playlist_track_uris(client, target_playlist.id)}

        to_add = [t for t in album_tracks if allow_duplicate or t.uri not in existing_uris]
        skipped = [t for t in album_tracks if t not in to_add]

        album_summary = {
            "id": album_obj["id"],
            "uri": album_obj["uri"],
            "name": album_obj["name"],
            "artists": [a["name"] for a in album_obj.get("artists", [])],
        }

        if dry_run:
            result = {
                "album": album_summary,
                "playlist": target_playlist.to_dict(),
                "would_add": [t.to_dict() for t in to_add],
                "would_skip_duplicates": [t.to_dict() for t in skipped],
            }
            if json_mode:
                emit_json(result)
            else:
                console.print(
                    f'[dry-run] Would add {len(to_add)} track(s) from "{album_summary["name"]}" to '
                    f'"{target_playlist.name}" ({len(skipped)} already present, skipped).'
                )
            return

        for i in range(0, len(to_add), 100):
            chunk = to_add[i : i + 100]
            if chunk:
                await client.post(f"/playlists/{target_playlist.id}/items", json={"uris": [t.uri for t in chunk]})

    result = {
        "album": album_summary,
        "playlist": target_playlist.to_dict(),
        "added": [t.to_dict() for t in to_add],
        "skipped_duplicates": [t.to_dict() for t in skipped],
    }
    if json_mode:
        emit_json(result)
    else:
        console.print(
            f'Added {len(to_add)} track(s) from "{album_summary["name"]}" to "{target_playlist.name}" '
            f'({len(skipped)} already present, skipped).'
        )


@playlist_app.command("dedupe")
@cli_command
async def playlist_dedupe(
    ctx: typer.Context,
    playlist: str = typer.Argument(..., help='Playlist name to deduplicate, e.g. "Driving".'),
    playlist_id: str | None = typer.Option(None, "--playlist-id", help="Exact Spotify playlist ID, bypassing name lookup."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be removed without making changes."),
) -> None:
    """Removes duplicate tracks from a playlist, keeping one occurrence of each.

    Spotify's current API can only remove *all* occurrences of a track URI at once (there
    is no per-position removal), so deduplicating works by removing every duplicated URI
    entirely and re-adding it once — the affected tracks end up at the end of the playlist
    rather than keeping their original position. Always safe to preview first with --dry-run.
    """
    json_mode = ctx.obj.json_mode
    async with build_client() as client:
        target = await _resolve_playlist_arg(client, playlist, playlist_id)
        uris = [u async for u in _iter_playlist_track_uris(client, target.id)]
        plan = dedupe_plan(uris)

        if plan["removed_count"] == 0:
            result = {"playlist": target.to_dict(), "applied": False, **plan}
            if json_mode:
                emit_json(result)
            else:
                console.print(f'"{target.name}" has no duplicate tracks.')
            return

        if dry_run:
            result = {"playlist": target.to_dict(), "applied": False, "dry_run": True, **plan}
            if json_mode:
                emit_json(result)
            else:
                console.print(
                    f'[dry-run] "{target.name}": would remove {plan["removed_count"]} duplicate '
                    f'occurrence(s) across {len(plan["duplicate_uris"])} track(s).'
                )
            return

        for uri in plan["duplicate_uris"]:
            await client.delete(f"/playlists/{target.id}/items", json={"items": [{"uri": uri}]})
        for i in range(0, len(plan["duplicate_uris"]), 100):
            chunk = plan["duplicate_uris"][i : i + 100]
            await client.post(f"/playlists/{target.id}/items", json={"uris": chunk})

    result = {"playlist": target.to_dict(), "applied": True, **plan}
    if json_mode:
        emit_json(result)
    else:
        console.print(
            f'Deduplicated "{target.name}": removed {plan["removed_count"]} duplicate occurrence(s) '
            f'({len(plan["duplicate_uris"])} track(s) moved to the end of the playlist).'
        )
