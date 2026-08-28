# spotify-cli

A small local command-line tool for managing your Spotify account — playlists, search,
your saved-tracks library, and the playback queue — built so it's just as usable by a
shell script or an AI coding agent (Claude Code, Codex, ...) as it is by a human.

- Python, `typer` + `httpx` (async), no heavyweight framework.
- OAuth Authorization Code + PKCE — no client secret is ever needed or stored.
- Config follows XDG conventions (`~/.config/spotify-cli/`); nothing is written into
  this repo.
- Every command works in human-readable mode and in `--json` mode.
- See [AGENTS.md](AGENTS.md) for how an AI agent should drive this tool.

## Why Python

This is a small, I/O-bound CLI: OAuth, a local callback server, and REST calls. Python's
`typer` + `httpx` gets a clean command hierarchy, async network calls, and a local HTTP
callback listener in a handful of small, readable files with a single `pyproject.toml`
and no build step. A .NET/C# version would work too, but would mean more ceremony
(project/solution files, more boilerplate for the same behavior) for no real benefit here
— so Python was picked for being the simpler, more maintainable option, not out of default
preference.

## What's implemented

| Command | Does |
|---|---|
| `spotify auth` | Interactive OAuth login (opens your browser) |
| `spotify auth status` | Shows whether you're logged in, and as whom |
| `spotify auth logout` | Deletes the stored token |
| `spotify search track "<query>" [--artist ...]` | Search for tracks |
| `spotify search artist "<query>"` | Search for artists |
| `spotify playlists` | List your playlists (alias for `playlist list`) |
| `spotify playlist list` | List your playlists |
| `spotify playlist show "<name>"` | Show a playlist's tracks |
| `spotify playlist create "<name>" [--public/--private] [--description ...]` | Create a playlist |
| `spotify playlist add "<track>" "<playlist>" [--artist ...] [--interactive] [--dry-run]` | Add a track, skipping duplicates |
| `spotify playlist remove "<track>" "<playlist>" [--artist ...] [--dry-run]` | Remove a track |
| `spotify playlist add-album "<album>" "<playlist>" [--artist ...] [--interactive] [--dry-run]` | Add every track of an album |
| `spotify playlist import "<playlist>" <file> [--interactive] [--stop-on-error] [--dry-run]` | Bulk-add tracks listed in a file |
| `spotify playlist dedupe "<playlist>" [--dry-run]` | Remove duplicate tracks |
| `spotify library add "<track>"` / `spotify liked add "<track>"` | Save a track to Liked Songs |
| `spotify library remove "<track>"` / `spotify liked remove "<track>"` | Remove a track from Liked Songs |
| `spotify library list` / `spotify liked list` | List Liked Songs |
| `spotify queue "<track>" [--artist ...] [--device-id ...]` | Add a track to the playback queue |
| `spotify devices` | List available playback devices |

Every command accepts a global `--json` flag (put it right after `spotify`, e.g.
`spotify --json playlist show "Driving"`) for machine-readable output. See
[AGENTS.md](AGENTS.md) for the exact JSON contract and exit codes.

### Bulk-adding a list of tracks: `spotify playlist import`

```bash
spotify playlist import "Driving" songs.txt
```

`songs.txt` is a plain-text file, one track per line:

```
# lines starting with # are comments
Black Hole Sun | Soundgarden
Would?
spotify:track:4iV5W9uYEdYUVa79Axb7Rh
```

- `Title | Artist` disambiguates the search; a bare title is fine too.
- A line that's already a `spotify:track:...` URI or an `open.spotify.com/track/...` URL is
  used directly, no search needed.
- A `.json` file (or `-` for stdin, if the piped content starts with `[`) works too — a
  top-level array of strings or of `{"track": "...", "artist": "..."}` / `{"uri": "..."}`
  objects. This is the friendlier format for another program or an AI agent to generate.
- Tracks already in the destination playlist are skipped automatically (matches `playlist
  add`'s duplicate handling). Tracks that can't be confidently matched are skipped and
  reported at the end, rather than aborting the whole import — add `--stop-on-error` to
  abort on the first one instead, or `--interactive` to be prompted for those (and for
  `playlist add`, or `playlist add-album`) instead of skipping them.
- `--dry-run` previews the whole batch — what would be added, skipped as a duplicate, or
  left unresolved — without changing anything.

### Choosing ambiguous matches interactively: `--interactive` / `-i`

`playlist add`, `playlist add-album`, `playlist import`, `library add`/`liked add`, and
`queue` all accept `--interactive` (or `-i`). Normally, an ambiguous track/album/playlist
match makes the command fail with candidates listed (exit code `3`) rather than guess. With
`--interactive`, you're shown a numbered table of candidates and prompted to pick one (or
`0` to cancel) instead. This only ever engages in a real terminal without `--json` — passed
anywhere else (a script, a pipe, alongside `--json`), it's ignored and the command falls
back to the normal non-interactive ambiguous-match behavior, so it's always safe to leave on
without risk of a script hanging waiting for input.

### Known limitation: no "find similar songs" primitive

Spotify removed public access to Recommendations, Related Artists, and Audio Features for
apps created after November 2024 (existing apps without prior extended-quota access lost
it too). There is no supported way for this CLI to ask Spotify "give me songs similar to
X" any more. This is why the CLI does not implement a `similar`/`recommend` command — it
would be built on an API Spotify no longer grants to apps like this one.

This isn't a blocker for the natural-language workflow this tool is designed for: an AI
agent (Claude, Codex, etc.) supplies the "similar songs" judgment itself, using its own
knowledge, and then drives this CLI's primitives (`search track`, `playlist show`,
`playlist add`) to search for and add the specific tracks it picked. See AGENTS.md for
that workflow end to end.

## Requirements

- Python 3.10+
- [`uv`](https://docs.astral.sh/uv/) (recommended) or `pip`
- A Spotify account (Premium is only required for `spotify queue`)
- A Spotify Developer app (free, see below)

## Spotify Developer Dashboard setup

1. Go to <https://developer.spotify.com/dashboard> and log in with your Spotify account.
2. Click **Create app**.
   - **App name / description**: anything, e.g. "Local CLI".
   - **Redirect URI**: `http://127.0.0.1:8888/callback`
     (must be exactly this if you keep the default port; see below if you change the port).
   - **Which API/SDKs are you planning to use?**: check **Web API**.
3. Save. Open the app's **Settings** and copy the **Client ID** — that's the only value
   you need. This tool uses Authorization Code + PKCE, so there is **no client secret to
   copy or store**.

Notes on the redirect URI, since Spotify's rules here changed in 2025:
- `localhost` is no longer accepted — it must be a loopback **IP literal**,
  `127.0.0.1` (or `[::1]` for IPv6).
- Plain `http://` is only allowed for loopback addresses; every other host requires `https://`.
- If you want to use a different local port, register `http://127.0.0.1:<port>/callback`
  in the dashboard and set `SPOTIFY_CLI_REDIRECT_PORT=<port>` in your config (see below) —
  or register the URI **without** a port (`http://127.0.0.1/callback`), which Spotify
  accepts for any port at runtime.

## Install

```bash
cd SpotifyHelper

# Recommended: installs an isolated `spotify` command onto your PATH via uv.
uv tool install --editable .

# Make sure uv's tool bin directory is on your PATH (usually ~/.local/bin):
uv tool update-shell   # or add it to your ~/.zshrc yourself

# Now from any directory:
spotify --help
```

Alternative, without `uv tool`:

```bash
cd SpotifyHelper
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
# `spotify` is now on PATH whenever this venv is active.
```

To upgrade after pulling changes: `uv tool install --editable . --force` (or `pip install -e .` again).

### Optional: install the Claude Code skill globally

If you use [Claude Code](https://claude.com/claude-code), this repo ships a `queue-song`
skill that lets Claude queue tracks on your behalf via this CLI. Once `spotify` is on
your PATH (see above), install the skill for every project on this machine with:

```bash
spotify install-skill
```

This copies the skill to `~/.claude/skills/queue-song/`. Pass `--force` to overwrite an
existing copy that's out of date.

## Configure

Copy the example config and fill in your Client ID:

```bash
mkdir -p ~/.config/spotify-cli
cp .env.example ~/.config/spotify-cli/.env
$EDITOR ~/.config/spotify-cli/.env   # set SPOTIFY_CLIENT_ID
```

Or export the environment variable instead (e.g. in `~/.zshrc`):

```bash
export SPOTIFY_CLIENT_ID=your_client_id_here
```

Real environment variables always take precedence over `~/.config/spotify-cli/.env`,
which in turn takes precedence over a `.env` in the current directory (handy for
development inside this repo).

Config directory layout (XDG):

```
~/.config/spotify-cli/
├── .env         # SPOTIFY_CLIENT_ID and optional overrides (you create this)
└── token.json   # created by `spotify auth`; mode 0600, never commit this
```

## Authenticate

```bash
spotify auth
```

This opens your browser to Spotify's consent screen, receives the OAuth callback on
`http://127.0.0.1:8888/callback` via a local one-shot HTTP server, exchanges the
authorization code for tokens (PKCE — no client secret involved), and stores the refresh
token at `~/.config/spotify-cli/token.json`. Access tokens are refreshed automatically
before they expire; you should not need to run `spotify auth` again unless you revoke
access or log out.

```bash
spotify auth status   # confirm you're logged in, and as whom
spotify auth logout   # delete the stored token
```

### Scopes requested

Only what the implemented features need — not Spotify's full scope list:

| Scope | Used for |
|---|---|
| `playlist-read-private` | Listing/reading your playlists, including private ones |
| `playlist-read-collaborative` | Reading collaborative playlists |
| `playlist-modify-public` | Creating/editing public playlists |
| `playlist-modify-private` | Creating/editing private playlists |
| `user-library-read` | Reading your Liked Songs |
| `user-library-modify` | Adding/removing Liked Songs |
| `user-read-playback-state` | Listing devices |
| `user-modify-playback-state` | Adding to the playback queue |

Search does not require any scope beyond a valid access token.

## Command examples

```bash
spotify auth
spotify search track "Black Hole Sun" --artist Soundgarden
spotify playlists
spotify playlist show "Driving"
spotify playlist create "90s Alt Rock" --private
spotify playlist add "Black Hole Sun" "Driving" --artist Soundgarden
spotify playlist add --dry-run "Would?" "Grunge"
spotify playlist remove "Black Hole Sun" "Driving"
spotify playlist add-album "Dirt" "Grunge" --artist "Alice in Chains"
spotify playlist import "Driving" songs.txt --dry-run
spotify playlist import "Driving" songs.txt --interactive
spotify playlist dedupe "Driving" --dry-run
spotify liked add "Would?"
spotify queue "Them Bones" --artist "Alice in Chains"
spotify devices

# Machine-readable output for scripts/agents:
spotify --json playlist show "Driving"
```

## Error handling & exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Generic/unexpected error |
| 2 | Requested resource not found (playlist, track, album, device, ...) |
| 3 | Ambiguous match — see `candidates` in `--json` output |
| 4 | Not authenticated / needs `spotify auth` again |
| 5 | Spotify API error (rate limit exhausted, Premium required, no active device, ...) |

The CLI automatically retries on HTTP 429 (honouring Spotify's `Retry-After` header) and
transparently refreshes expired access tokens; you shouldn't normally see either surface
as an error.

## Development

```bash
cd SpotifyHelper
uv sync              # installs runtime + dev dependencies into .venv
uv run pytest        # runs the (network-free) unit tests for matching/dedupe logic
uv run spotify --help
```

## Project layout

```
src/spotify_cli/
├── cli.py            # Typer app assembly, global --json flag, command aliases
├── cli_support.py     # async-command glue + centralized error -> exit-code handling
├── config.py          # XDG config loading (SPOTIFY_CLIENT_ID, redirect URI, ...)
├── auth.py            # OAuth PKCE flow, local callback server, token storage/refresh
├── api_client.py       # async Spotify Web API client (retries, pagination, 429/401 handling)
├── matching.py         # scoring/auto-select logic, dedupe planning (pure, unit-tested)
├── resolution.py        # turns a name/query into a Track/album/Playlist via search + matching.py,
│                        # including the --interactive disambiguation prompt
├── track_list.py         # parses `playlist import` files (plain text / JSON; pure, unit-tested)
├── models.py           # Track / Playlist / Device dataclasses
├── output.py           # human vs --json rendering, tables, interactive candidate prompt
└── commands/           # one module per command group (auth, search, playlist, library, queue)
```
