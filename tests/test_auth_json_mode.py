"""Guards the --json contract on the one command that reaches it through a group
callback rather than a plain Typer command.
"""

import json

import typer
from typer.testing import CliRunner

from spotify_cli.cli import app
from spotify_cli.cli_support import _find_json_mode
from spotify_cli.commands import auth as auth_cmd
from spotify_cli.config import Settings
from spotify_cli.errors import AuthError, ExitCode

SETTINGS = Settings(client_id="x", redirect_uri="http://127.0.0.1:8888/callback")


def test_json_auth_reports_failure_as_json(monkeypatch):
    """'spotify --json auth' must answer with an {"error": ...} document.

    'auth' with no subcommand runs through auth_main, which hands its context to
    _login by hand. Typer passes contexts by keyword, and the object it hands a
    group callback is a plain click Context, so cli_command's positional lookup
    (isinstance(a, typer.Context)) never matches it. Calling _login(ctx) instead of
    _login(ctx=ctx) therefore reports human mode and prints prose to stderr — the
    caller gets nothing on stdout to parse. This test fails on that regression.
    """
    monkeypatch.setattr(auth_cmd, "load_settings", lambda: SETTINGS)

    def _refuse(settings):
        raise AuthError("login refused")

    monkeypatch.setattr(auth_cmd, "run_login_flow", _refuse)

    result = CliRunner().invoke(app, ["--json", "auth"])

    assert result.exit_code == ExitCode.AUTH_REQUIRED
    assert json.loads(result.stdout) == {"error": "login refused"}


def _captured_group_context():
    """Returns the context object Typer actually hands the 'auth' group callback.

    Built by invoking the app rather than constructed by hand: a click Context needs a
    Command to attach to, and the point of the test is to pin down the real object.
    """
    captured = {}

    def _capture(ctx):
        captured["ctx"] = ctx
        raise SystemExit(0)

    runner = CliRunner()
    original = auth_cmd._login
    try:
        auth_cmd._login = lambda *a, **kw: _capture(kw.get("ctx") or a[0])
        runner.invoke(app, ["--json", "auth"])
    finally:
        auth_cmd._login = original
    return captured["ctx"]


def test_group_callback_context_is_not_a_typer_context():
    """Pins the reason _find_json_mode can't just match typer.Context.

    Typer hands a group callback a plain click Context. If this ever starts being a
    typer.Context, the base-class match in cli_support is no longer load-bearing.
    """
    ctx = _captured_group_context()
    assert not isinstance(ctx, typer.Context)
    assert isinstance(ctx, typer.Context.__bases__[0])


def test_find_json_mode_reads_context_passed_either_way():
    """json_mode must survive both a keyword and a positional hand-call.

    auth_main passes ctx by keyword; the positional branch is the safety net that was
    silently returning False before, dropping --json output on the floor.
    """
    ctx = _captured_group_context()
    assert ctx.obj.json_mode is True

    assert _find_json_mode((), {"ctx": ctx}) is True
    assert _find_json_mode((ctx,), {}) is True
