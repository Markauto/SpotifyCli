"""Installs this project's Claude Code skills globally for the current user, so any
Claude Code session on the machine can drive the CLI without being run from inside this
repo (as long as `spotify` is on PATH).
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import typer

from ..cli_support import cli_command
from ..errors import ConfigError
from ..output import console, emit_json


def _bundled_skill_names() -> list[str]:
    skills_dir = resources.files("spotify_cli").joinpath("skills")
    return sorted(entry.name for entry in skills_dir.iterdir() if entry.joinpath("SKILL.md").is_file())


def _bundled_skill_text(name: str) -> str:
    return resources.files("spotify_cli").joinpath("skills", name, "SKILL.md").read_text()


def _target_path(name: str) -> Path:
    return Path.home() / ".claude" / "skills" / name / "SKILL.md"


@cli_command
def install_skill(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing installed skill files."),
) -> None:
    """Copies every bundled skill to ~/.claude/skills/<name>/SKILL.md, making them
    available to Claude Code sessions anywhere on this machine, not just inside this repo."""
    json_mode = ctx.obj.json_mode
    planned: list[tuple[str, Path, str, bool]] = []
    conflicts: list[Path] = []

    for name in _bundled_skill_names():
        target = _target_path(name)
        content = _bundled_skill_text(name)
        if target.exists() and target.read_text() == content:
            planned.append((name, target, content, False))
        elif target.exists() and not force:
            conflicts.append(target)
        else:
            planned.append((name, target, content, True))

    # Check every target before writing any, so a conflict can't leave a half-install.
    if conflicts:
        listed = ", ".join(str(p) for p in conflicts)
        raise ConfigError(
            f"{listed} already exist(s) and differ(s) from the bundled skill. Re-run with --force to overwrite."
        )

    for _name, target, content, changed in planned:
        if changed:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

    skills = [{"name": name, "path": str(target), "changed": changed} for name, target, _content, changed in planned]
    changed_count = sum(1 for s in skills if s["changed"])

    if json_mode:
        emit_json({"installed": True, "skills": skills, "changed": changed_count})
        return

    for skill in skills:
        if skill["changed"]:
            console.print(f"Installed [bold]{skill['name']}[/bold] skill to {skill['path']}.")
        else:
            console.print(f"[bold]{skill['name']}[/bold] already installed at {skill['path']} (no changes).")
    if changed_count:
        console.print("Restart Claude Code (or start a new session) to pick it up.")
