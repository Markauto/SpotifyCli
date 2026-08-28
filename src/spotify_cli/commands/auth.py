from __future__ import annotations

import typer

from ..api_client import build_client
from ..auth import TokenStore, run_login_flow
from ..cli_support import cli_command
from ..config import load_settings, token_path
from ..errors import ExitCode
from ..output import console, emit_json, err_console

auth_app = typer.Typer(help="Authenticate this CLI with your Spotify account.")


@auth_app.callback(invoke_without_command=True)
def auth_main(ctx: typer.Context) -> None:
    """Running 'spotify auth' with no subcommand starts the login flow."""
    if ctx.invoked_subcommand is None:
        # Keyword, not positional: Typer hands a group callback a plain click Context,
        # which cli_command's positional isinstance(typer.Context) scan never matches —
        # so a positional call silently loses --json mode.
        _login(ctx=ctx)


@cli_command
def _login(ctx: typer.Context) -> None:
    json_mode = ctx.obj.json_mode
    settings = load_settings()
    token_response = run_login_flow(settings)
    store = TokenStore(token_path(), settings)
    store.save(token_response)

    result = {
        "authenticated": True,
        "scope": token_response.get("scope", ""),
        "config_dir": str(token_path().parent),
    }
    if json_mode:
        emit_json(result)
    else:
        console.print("[bold green]Authenticated successfully.[/bold green]")
        console.print(f"Granted scopes: {token_response.get('scope', '')}")
        console.print(f"Token stored at: {token_path()}")


@auth_app.command("status")
@cli_command
async def auth_status(ctx: typer.Context) -> None:
    """Shows whether the CLI is authenticated, and verifies the token against /me."""
    json_mode = ctx.obj.json_mode
    settings = load_settings()
    store = TokenStore(token_path(), settings)

    if not store.has_token():
        if json_mode:
            emit_json({"authenticated": False})
        else:
            err_console.print("Not authenticated. Run 'spotify auth' to log in.")
        raise typer.Exit(code=ExitCode.AUTH_REQUIRED)

    async with build_client(settings) as client:
        me = await client.get("/me")

    result = {
        "authenticated": True,
        "user_id": me.get("id"),
        "display_name": me.get("display_name"),
        "scope": store.scope(),
        "token_path": str(token_path()),
    }
    if json_mode:
        emit_json(result)
    else:
        console.print("[bold green]Authenticated[/bold green]")
        console.print(f"Logged in as: {me.get('display_name') or me.get('id')} ({me.get('id')})")
        console.print(f"Granted scopes: {store.scope()}")


@auth_app.command("logout")
@cli_command
def auth_logout(ctx: typer.Context) -> None:
    """Deletes the locally stored refresh/access token."""
    json_mode = ctx.obj.json_mode
    settings = load_settings()
    store = TokenStore(token_path(), settings)
    had_token = store.has_token()
    store.clear()

    if json_mode:
        emit_json({"logged_out": True, "had_token": had_token})
    else:
        console.print("Logged out." if had_token else "Already logged out.")
