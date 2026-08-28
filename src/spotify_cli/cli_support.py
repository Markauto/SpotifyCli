"""Shared plumbing for Typer command functions: runs async command bodies via asyncio.run,
and centralizes error -> (message, exit code) handling so individual commands don't each
need their own try/except.
"""

from __future__ import annotations

import asyncio
import functools
import inspect

import httpx
import typer

from .errors import ApiError, ExitCode, SpotifyCliError
from .output import print_cli_error


# typer.Context subclasses click's Context, and Typer hands a group callback the plain
# click one — match the base so a context is found whichever form it arrives in.
_CONTEXT_CLASS = typer.Context.__bases__[0]


def _find_json_mode(args: tuple, kwargs: dict) -> bool:
    ctx = kwargs.get("ctx")
    if ctx is None:
        ctx = next((a for a in args if isinstance(a, _CONTEXT_CLASS)), None)
    if ctx is not None and ctx.obj is not None:
        return bool(getattr(ctx.obj, "json_mode", False))
    return False


def cli_command(func):
    """Wraps a Typer command callback (sync or async) with uniform error handling.
    Preserves the original signature via functools.wraps so Typer's introspection
    (which follows __wrapped__) still sees the real parameters.
    """
    is_async = asyncio.iscoroutinefunction(func)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        json_mode = _find_json_mode(args, kwargs)
        try:
            if is_async:
                return asyncio.run(func(*args, **kwargs))
            return func(*args, **kwargs)
        except SpotifyCliError as e:
            print_cli_error(e, json_mode)
            raise typer.Exit(code=e.exit_code)
        except httpx.HTTPError as e:
            print_cli_error(ApiError(f"Network error talking to Spotify: {e}"), json_mode)
            raise typer.Exit(code=ExitCode.API_ERROR)

    return wrapper
