from __future__ import annotations

import typer

from ..api_client import build_client
from ..cli_support import cli_command
from ..models import Track
from ..output import console, emit_json, render_tracks_table

search_app = typer.Typer(help="Search Spotify's catalog.")


@search_app.command("track")
@cli_command
async def search_track(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Track title to search for."),
    artist: str | None = typer.Option(None, "--artist", help="Filter/boost results by artist name."),
    limit: int = typer.Option(10, "--limit", min=1, max=10, help="Max results to return (Spotify caps this at 10)."),
) -> None:
    """Searches for tracks. Search does not require any OAuth scope beyond a valid token."""
    json_mode = ctx.obj.json_mode
    q = f'track:"{query}" artist:"{artist}"' if artist else query

    async with build_client() as client:
        data = await client.get("/search", params={"q": q, "type": "track", "limit": limit})

    tracks = [Track.from_api(t) for t in (data.get("tracks") or {}).get("items", [])]

    if json_mode:
        emit_json({"query": query, "artist": artist, "results": [t.to_dict() for t in tracks]})
    else:
        if not tracks:
            console.print("No tracks found.")
        else:
            render_tracks_table(tracks, title=f"Search results for '{query}'")


@search_app.command("artist")
@cli_command
async def search_artist(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Artist name to search for."),
    limit: int = typer.Option(10, "--limit", min=1, max=10, help="Max results to return (Spotify caps this at 10)."),
) -> None:
    """Searches for artists — useful for confirming exact spelling/naming before a track search."""
    json_mode = ctx.obj.json_mode

    async with build_client() as client:
        data = await client.get("/search", params={"q": query, "type": "artist", "limit": limit})

    items = (data.get("artists") or {}).get("items", [])
    results = [{"id": a["id"], "uri": a["uri"], "name": a["name"], "genres": a.get("genres", []), "popularity": a.get("popularity")} for a in items]

    if json_mode:
        emit_json({"query": query, "results": results})
    else:
        if not results:
            console.print("No artists found.")
            return
        from rich.table import Table

        table = Table(title=f"Artist search results for '{query}'", show_header=True, header_style="bold")
        table.add_column("Name")
        table.add_column("Genres")
        table.add_column("URI", style="dim")
        for a in results:
            table.add_row(a["name"], ", ".join(a["genres"][:4]), a["uri"])
        console.print(table)
