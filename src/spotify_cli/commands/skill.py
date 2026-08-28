"""Installs this project's `queue-song` Claude Code skill globally for the current user,
so any Claude Code session on the machine can queue songs without being run from inside
this repo (as long as `spotify` is on PATH).
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import typer

from ..cli_support import cli_command
from ..errors import ConfigError
from ..output import console, emit_json

SKILL_NAME = "queue-song"


def _bundled_skill_text() -> str:
    return resources.files("spotify_cli").joinpath("skills", SKILL_NAME, "SKILL.md").read_text()


def _target_path() -> Path:
    return Path.home() / ".claude" / "skills" / SKILL_NAME / "SKILL.md"


@cli_command
def install_skill(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing installed skill file."),
) -> None:
    """Copies the queue-song skill to ~/.claude/skills/queue-song/SKILL.md, making it
    available to Claude Code sessions anywhere on this machine, not just inside this repo."""
    json_mode = ctx.obj.json_mode
    target = _target_path()
    content = _bundled_skill_text()

    if target.exists() and target.read_text() == content:
        result = {"installed": True, "path": str(target), "changed": False}
        if json_mode:
            emit_json(result)
        else:
            console.print(f"Already installed at [bold]{target}[/bold] (no changes).")
        return

    if target.exists() and not force:
        raise ConfigError(
            f"{target} already exists and differs from the bundled skill. Re-run with --force to overwrite."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)

    result = {"installed": True, "path": str(target), "changed": True}
    if json_mode:
        emit_json(result)
    else:
        console.print(f"Installed queue-song skill to [bold]{target}[/bold].")
        console.print("Restart Claude Code (or start a new session) to pick it up.")
