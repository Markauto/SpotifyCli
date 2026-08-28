"""Human vs. --json output. In --json mode, stdout is always exactly one JSON document
(the result, or {"error": ...} on failure) so an agent never has to separate prose from
data. In human mode, results go to stdout as text/tables and errors go to stderr.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()
err_console = Console(stderr=True)


@dataclass
class AppContext:
    json_mode: bool = False


def emit_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


def print_cli_error(exc, json_mode: bool) -> None:
    if json_mode:
        payload: dict[str, Any] = {"error": exc.message}
        candidates = getattr(exc, "candidates", None)
        if candidates:
            payload["candidates"] = candidates
        status_code = getattr(exc, "status_code", None)
        if status_code:
            payload["status_code"] = status_code
        emit_json(payload)
        return

    err_console.print(f"[bold red]Error:[/bold red] {exc.message}")
    candidates = getattr(exc, "candidates", None)
    if candidates:
        table = Table(show_header=True, header_style="bold")
        keys = [k for k in candidates[0].keys() if k not in ("uri", "id")]
        for k in keys:
            table.add_column(k)
        for c in candidates:
            table.add_row(*(str(c.get(k, "")) for k in keys))
        err_console.print(table)


def prompt_pick_candidate(candidates: list[dict], noun: str = "item") -> int | None:
    """Prints a numbered table of candidates and prompts the user to pick one.
    Returns the zero-based index chosen, or None if the user cancels (enters 0).
    Callers are responsible for only invoking this in an interactive, non-JSON context.
    """
    from rich.prompt import Prompt

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right")
    keys = [k for k in candidates[0].keys() if k not in ("uri", "id", "score")]
    for k in keys:
        table.add_column(k)
    for i, c in enumerate(candidates, start=1):
        table.add_row(str(i), *(str(c.get(k, "")) for k in keys))
    console.print(table)

    choices = [str(i) for i in range(0, len(candidates) + 1)]
    raw = Prompt.ask(f"Which {noun}? (1-{len(candidates)}, 0 to cancel)", choices=choices, default="0")
    idx = int(raw)
    return None if idx == 0 else idx - 1


def render_tracks_table(tracks: list, title: str = "Tracks") -> None:
    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("Track")
    table.add_column("Artist")
    table.add_column("Album")
    table.add_column("URI", style="dim")
    for i, t in enumerate(tracks, start=1):
        table.add_row(str(i), t.name, t.artist_str, t.album or "", t.uri)
    console.print(table)


def render_playlists_table(playlists: list, title: str = "Playlists") -> None:
    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Owner")
    table.add_column("Tracks", justify="right")
    table.add_column("Visibility")
    table.add_column("ID", style="dim")
    for p in playlists:
        visibility = "collaborative" if p.collaborative else ("public" if p.public else "private")
        table.add_row(p.name, p.owner, str(p.total_tracks), visibility, p.id)
    console.print(table)
