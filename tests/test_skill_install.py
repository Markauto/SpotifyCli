from types import SimpleNamespace

import pytest

from spotify_cli.commands.skill import _agent_target_dirs, _bundled_skill_names, _bundled_skill_text, install_skill
from spotify_cli.errors import ConfigError
from spotify_cli.output import AppContext


def make_ctx(json_mode=False):
    return SimpleNamespace(obj=AppContext(json_mode=json_mode))


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


def agent_dir_names(home):
    return [skills_dir.relative_to(home).parts[0] for _agent, skills_dir in _agent_target_dirs()]


def target_paths(home, name):
    return [home / dir_name / "skills" / name / "SKILL.md" for dir_name in agent_dir_names(home)]


def test_bundles_the_expected_skills():
    assert set(_bundled_skill_names()) >= {"queue-song", "make-playlist"}


def test_installs_every_bundled_skill_for_every_agent_when_missing(fake_home):
    install_skill.__wrapped__(make_ctx(), force=False)

    for name in _bundled_skill_names():
        for installed in target_paths(fake_home, name):
            assert installed.exists()
            assert installed.read_text() == _bundled_skill_text(name)


def test_installs_to_claude_and_codex_directories(fake_home):
    install_skill.__wrapped__(make_ctx(), force=False)

    for name in _bundled_skill_names():
        assert (fake_home / ".claude" / "skills" / name / "SKILL.md").exists()
        assert (fake_home / ".agents" / "skills" / name / "SKILL.md").exists()


def test_idempotent_when_identical(fake_home):
    install_skill.__wrapped__(make_ctx(), force=False)
    # Second run should not raise even without --force.
    install_skill.__wrapped__(make_ctx(), force=False)


def test_refuses_to_overwrite_without_force(fake_home):
    installed = fake_home / ".claude" / "skills" / "queue-song" / "SKILL.md"
    installed.parent.mkdir(parents=True)
    installed.write_text("custom content")

    with pytest.raises(ConfigError):
        install_skill.__wrapped__(make_ctx(), force=False)

    assert installed.read_text() == "custom content"


def test_conflict_leaves_other_skills_untouched(fake_home):
    """A conflict on one skill/agent must abort before anything is written, not half-install."""
    conflicting = fake_home / ".claude" / "skills" / "queue-song" / "SKILL.md"
    conflicting.parent.mkdir(parents=True)
    conflicting.write_text("custom content")

    with pytest.raises(ConfigError):
        install_skill.__wrapped__(make_ctx(), force=False)

    assert not (fake_home / ".claude" / "skills" / "make-playlist" / "SKILL.md").exists()
    assert not (fake_home / ".agents" / "skills" / "queue-song" / "SKILL.md").exists()
    assert not (fake_home / ".agents" / "skills" / "make-playlist" / "SKILL.md").exists()


def test_overwrites_with_force(fake_home):
    installed = fake_home / ".claude" / "skills" / "queue-song" / "SKILL.md"
    installed.parent.mkdir(parents=True)
    installed.write_text("custom content")

    install_skill.__wrapped__(make_ctx(), force=True)

    assert installed.read_text() == _bundled_skill_text("queue-song")
    assert (fake_home / ".agents" / "skills" / "queue-song" / "SKILL.md").read_text() == _bundled_skill_text(
        "queue-song"
    )
