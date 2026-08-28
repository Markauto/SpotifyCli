from types import SimpleNamespace

import pytest

from spotify_cli.commands.skill import _bundled_skill_text, install_skill
from spotify_cli.errors import ConfigError
from spotify_cli.output import AppContext


def make_ctx(json_mode=False):
    return SimpleNamespace(obj=AppContext(json_mode=json_mode))


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


def target_path(home):
    return home / ".claude" / "skills" / "queue-song" / "SKILL.md"


def test_installs_when_missing(fake_home):
    install_skill.__wrapped__(make_ctx(), force=False)
    installed = target_path(fake_home)
    assert installed.exists()
    assert installed.read_text() == _bundled_skill_text()


def test_idempotent_when_identical(fake_home):
    install_skill.__wrapped__(make_ctx(), force=False)
    # Second run should not raise even without --force.
    install_skill.__wrapped__(make_ctx(), force=False)


def test_refuses_to_overwrite_without_force(fake_home):
    installed = target_path(fake_home)
    installed.parent.mkdir(parents=True)
    installed.write_text("custom content")

    with pytest.raises(ConfigError):
        install_skill.__wrapped__(make_ctx(), force=False)

    assert installed.read_text() == "custom content"


def test_overwrites_with_force(fake_home):
    installed = target_path(fake_home)
    installed.parent.mkdir(parents=True)
    installed.write_text("custom content")

    install_skill.__wrapped__(make_ctx(), force=True)

    assert installed.read_text() == _bundled_skill_text()
