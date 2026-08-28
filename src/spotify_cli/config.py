"""Configuration loading, following XDG conventions.

Precedence (highest first): real process environment variables, then
~/.config/spotify-cli/.env, then ./.env in the current directory (handy for
local development). Nothing here ever stores a client secret — the CLI uses
Authorization Code + PKCE, so only a client ID is required.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .errors import ConfigError

APP_NAME = "spotify-cli"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def token_path() -> Path:
    return config_dir() / "token.json"


@dataclass(frozen=True)
class Settings:
    client_id: str
    redirect_uri: str
    api_base: str = "https://api.spotify.com/v1"
    accounts_base: str = "https://accounts.spotify.com"
    request_timeout: float = 15.0


_loaded_dotenv = False


def _ensure_dotenv_loaded() -> None:
    global _loaded_dotenv
    if _loaded_dotenv:
        return
    load_dotenv(config_dir() / ".env")
    load_dotenv(Path.cwd() / ".env", override=False)
    _loaded_dotenv = True


def load_settings() -> Settings:
    _ensure_dotenv_loaded()

    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    if not client_id:
        raise ConfigError(
            "SPOTIFY_CLIENT_ID is not set. Create a Spotify app at "
            "https://developer.spotify.com/dashboard, then set SPOTIFY_CLIENT_ID "
            f"in your environment or in {config_dir() / '.env'} (see .env.example)."
        )

    port = os.environ.get("SPOTIFY_CLI_REDIRECT_PORT", "8888").strip()
    default_redirect = f"http://127.0.0.1:{port}/callback"
    redirect_uri = os.environ.get("SPOTIFY_CLI_REDIRECT_URI", default_redirect).strip()

    return Settings(client_id=client_id, redirect_uri=redirect_uri)
