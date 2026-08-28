"""Spotify OAuth: Authorization Code + PKCE, with local-loopback redirect capture.

Why PKCE and not the classic Authorization Code flow with a client secret:
this is a local CLI that cannot safely keep a confidential secret, and Spotify
retired the Implicit Grant flow (enforced from 2025-11-27). PKCE needs only a
public client ID plus a per-login code_verifier/code_challenge pair, so no
client secret ever needs to exist or be stored.

Why 127.0.0.1 and not localhost: Spotify's current redirect URI validation
rejects the `localhost` hostname outright and requires HTTPS for all redirect
URIs *except* loopback IP literals (127.0.0.1 / [::1]), where plain HTTP is
permitted. This module always builds/expects a loopback URI.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .config import Settings
from .errors import AuthError, AuthRequiredError

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

# The minimum scopes needed for the features this CLI implements — deliberately
# not the full Spotify scope list. See README.md for the mapping of scope -> feature.
SCOPES = [
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-public",
    "playlist-modify-private",
    "user-library-read",
    "user-library-modify",
    "user-read-playback-state",
    "user-modify-playback-state",
]


def _make_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        expected_path = urlparse(self.server.redirect_uri).path or "/callback"
        if parsed.path != expected_path:
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        self.server.auth_result = {
            "code": params.get("code", [None])[0],
            "state": params.get("state", [None])[0],
            "error": params.get("error", [None])[0],
        }

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if self.server.auth_result.get("error"):
            body = (
                "<html><body><h2>Spotify authorization failed</h2>"
                f"<p>{self.server.auth_result['error']}</p>"
                "<p>You can close this tab and return to the terminal.</p></body></html>"
            )
        else:
            body = (
                "<html><body><h2>Spotify authorization complete</h2>"
                "<p>You can close this tab and return to the terminal.</p></body></html>"
            )
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format, *args):  # noqa: A002 - silence default stderr logging
        pass


def run_login_flow(settings: Settings, timeout: float = 300.0) -> dict:
    """Runs one interactive PKCE login and returns the raw token response."""

    verifier, challenge = _make_pkce_pair()
    state = secrets.token_urlsafe(16)
    redirect = urlparse(settings.redirect_uri)
    if redirect.hostname not in ("127.0.0.1", "::1"):
        raise AuthError(
            f"Redirect URI '{settings.redirect_uri}' is not a loopback address. "
            "Spotify requires http://127.0.0.1:<port>/callback for local apps."
        )

    server = HTTPServer((redirect.hostname, redirect.port or 80), _CallbackHandler)
    server.redirect_uri = settings.redirect_uri
    server.auth_result = None
    server.timeout = timeout

    query = {
        "client_id": settings.client_id,
        "response_type": "code",
        "redirect_uri": settings.redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "scope": " ".join(SCOPES),
        "state": state,
    }
    auth_url = f"{AUTHORIZE_URL}?{urlencode(query)}"

    print("Opening your browser to authorize this app with Spotify...")
    print(f"If it doesn't open automatically, visit:\n  {auth_url}\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    server.handle_request()
    server.server_close()
    result = server.auth_result

    if result is None:
        raise AuthError(f"Timed out waiting for the Spotify redirect after {int(timeout)}s. Try 'spotify auth' again.")
    if result.get("error"):
        raise AuthError(f"Spotify authorization was denied or failed: {result['error']}")
    if result.get("state") != state:
        raise AuthError("OAuth state mismatch on callback; aborting for safety. Try 'spotify auth' again.")
    code = result.get("code")
    if not code:
        raise AuthError("No authorization code received from Spotify.")

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.redirect_uri,
                "client_id": settings.client_id,
                "code_verifier": verifier,
            },
        )
    if resp.status_code != 200:
        raise AuthError(f"Token exchange failed ({resp.status_code}): {resp.text}")
    return resp.json()


class TokenStore:
    """Persists tokens at ~/.config/spotify-cli/token.json (mode 0600) and refreshes on demand."""

    def __init__(self, path: Path, settings: Settings):
        self.path = path
        self.settings = settings
        self._data: dict | None = None

    def save(self, token_response: dict) -> None:
        now = time.time()
        previous = self._read()
        refresh_token = token_response.get("refresh_token") or (previous or {}).get("refresh_token")
        data = {
            "access_token": token_response["access_token"],
            "refresh_token": refresh_token,
            "expires_at": now + float(token_response.get("expires_in", 3600)),
            "scope": token_response.get("scope", (previous or {}).get("scope", "")),
            "token_type": token_response.get("token_type", "Bearer"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        self.path.write_text(json.dumps(data, indent=2))
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        self._data = data

    def _read(self) -> dict | None:
        if self._data is not None:
            return self._data
        if not self.path.exists():
            return None
        self._data = json.loads(self.path.read_text())
        return self._data

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
        self._data = None

    def has_token(self) -> bool:
        return self._read() is not None

    def scope(self) -> str:
        data = self._read()
        return (data or {}).get("scope", "")

    async def get_access_token(self, force_refresh: bool = False) -> str:
        data = self._read()
        if data is None:
            raise AuthRequiredError("Not authenticated. Run 'spotify auth' first.")

        if not force_refresh and data["expires_at"] - time.time() > 60:
            return data["access_token"]

        refresh_token = data.get("refresh_token")
        if not refresh_token:
            raise AuthRequiredError("No refresh token stored. Run 'spotify auth' again.")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self.settings.client_id,
                },
            )
        if resp.status_code != 200:
            raise AuthRequiredError(
                f"Failed to refresh Spotify token ({resp.status_code}). Run 'spotify auth' again."
            )
        payload = resp.json()
        if "refresh_token" not in payload:
            payload["refresh_token"] = refresh_token
        self.save(payload)
        return payload["access_token"]
