"""Installs this project's skills globally for the current user, so any Claude Code or
Codex CLI session on the machine can drive the CLI without being run from inside this
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


def _agent_target_dirs() -> list[tuple[str, Path]]:
    """Personal skill directories for each agent that reads the SKILL.md format."""
    home = Path.home()
    return [
        ("Claude Code", home / ".claude" / "skills"),
        # Codex CLI's skills feature reads personal skills from ~/.agents/skills.
        ("Codex", home / ".agents" / "skills"),
    ]


def _target_paths(name: str) -> list[tuple[str, Path]]:
    return [(agent, skills_dir / name / "SKILL.md") for agent, skills_dir in _agent_target_dirs()]


@cli_command
def install_skill(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing installed skill files."),
) -> None:
    """Copies every bundled skill to ~/.claude/skills/<name>/SKILL.md and
    ~/.agents/skills/<name>/SKILL.md, making them available to Claude Code and Codex CLI
    sessions anywhere on this machine, not just inside this repo."""
    json_mode = ctx.obj.json_mode
    planned: list[tuple[str, str, Path, bool]] = []  # agent, name, target, changed
    conflicts: list[Path] = []

    for name in _bundled_skill_names():
        content = _bundled_skill_text(name)
        for agent, target in _target_paths(name):
            if target.exists() and target.read_text() == content:
                planned.append((agent, name, target, False))
            elif target.exists() and not force:
                conflicts.append(target)
            else:
                planned.append((agent, name, target, True))

    # Check every target before writing any, so a conflict can't leave a half-install.
    if conflicts:
        listed = ", ".join(str(p) for p in conflicts)
        raise ConfigError(
            f"{listed} already exist(s) and differ(s) from the bundled skill. Re-run with --force to overwrite."
        )

    for _agent, name, target, changed in planned:
        if changed:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_bundled_skill_text(name))

    skills = [{"agent": agent, "name": name, "path": str(target), "changed": changed} for agent, name, target, changed in planned]
    changed_count = sum(1 for s in skills if s["changed"])

    if json_mode:
        emit_json({"installed": True, "skills": skills, "changed": changed_count})
        return

    for skill in skills:
        if skill["changed"]:
            console.print(f"Installed [bold]{skill['name']}[/bold] skill for {skill['agent']} to {skill['path']}.")
        else:
            console.print(
                f"[bold]{skill['name']}[/bold] already installed for {skill['agent']} at {skill['path']} (no changes)."
            )
    if changed_count:
        console.print("Restart Claude Code / Codex (or start a new session) to pick it up.")
