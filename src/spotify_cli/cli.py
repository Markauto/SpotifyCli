"""Root Typer app: wires together auth, search, playlist, library and queue commands."""

from __future__ import annotations

import typer

from .commands.auth import auth_app
from .commands.library import library_app
from .commands.playlist import playlist_app, playlist_list
from .commands.queue import list_devices, now_playing, queue_track
from .commands.search import search_app
from .commands.skill import install_skill
from .output import AppContext

app = typer.Typer(
    name="spotify",
    help="Manage your Spotify account from the terminal — playlists, search, library and queue. "
    "Built to be driven by a human shell or an AI coding agent (see AGENTS.md).",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON on stdout instead of human-readable text."
    ),
) -> None:
    ctx.obj = AppContext(json_mode=json_output)


app.add_typer(auth_app, name="auth")
app.add_typer(search_app, name="search")
app.add_typer(playlist_app, name="playlist")
app.add_typer(library_app, name="library")
# "liked" is an alias for "library" (spotify liked add "..."), matching common phrasing
# for Spotify's Liked Songs feature.
app.add_typer(library_app, name="liked")

# Convenience top-level aliases matching the project's example commands.
app.command("playlists", help="Alias for 'playlist list'.")(playlist_list)
app.command("queue", help="Add a track to the playback queue.")(queue_track)
app.command("devices", help="List available playback devices.")(list_devices)
app.command("now", help="Show what's currently playing.")(now_playing)
app.command("install-skill", help="Install the queue-song Claude Code skill globally for this user.")(install_skill)


if __name__ == "__main__":
    app()
