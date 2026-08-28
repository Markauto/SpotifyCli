# AGENTS.md — driving `spotify-cli` as an AI agent

This file is for AI coding agents (Claude Code, Codex, or similar) invoking the `spotify`
CLI on the user's behalf — for example, turning a request like "find 15 songs similar to
Alice in Chains and Soundgarden and add them to my Grunge playlist, avoiding duplicates"
into a sequence of CLI calls.

The CLI itself does **no** natural-language parsing. It exposes deterministic primitives;
you are the one translating intent into calls, choosing specific tracks, and sequencing
operations.

## The contract: always use `--json`

Put `--json` right after `spotify`. When present:

- **stdout is always exactly one JSON document** — either the successful result, or
  `{"error": "...", "candidates": [...]}` on failure. Never mixed with prose.
- Parse stdout as JSON unconditionally; don't try to scrape human-formatted text.
- Check the **process exit code** first, before parsing — it tells you the outcome class
  without needing to inspect the JSON body:

| Exit code | Meaning | What to do |
|---|---|---|
| `0` | Success | Parse stdout as the result |
| `1` | Generic/unexpected error | Read `error` in stdout; usually not retryable automatically |
| `2` | Not found (playlist, track, album, device) | Don't guess — search or list first, then retry with a better query or an explicit ID |
| `3` | Ambiguous match | Read `candidates` in stdout and either ask the user, or pick the best candidate yourself and retry with `--artist`, `--track-uri`, `--album-uri`, or `--playlist-id` to pin it down |
| `4` | Not authenticated | Tell the user to run `spotify auth` interactively — you cannot complete OAuth login on their behalf, it requires their browser |
| `5` | Spotify API error (rate limit exhausted, Premium required, no active device, ...) | The message explains which; usually not fixable by retrying immediately |

Example:

```bash
spotify --json playlist show "Driving"
```

```json
{
  "playlist": { "id": "...", "uri": "...", "name": "Driving", "owner": "...", "public": true, "collaborative": false, "total_tracks": 42, "snapshot_id": "..." },
  "tracks": [ { "id": "...", "uri": "spotify:track:...", "name": "Black Hole Sun", "artists": ["Soundgarden"], "album": "Superunknown", "duration_ms": 318933 } ]
}
```

One caveat on that shape: **don't use `snapshot_id` for concurrency control.** Spotify's read
endpoints serve a stale value — after a playlist is mutated it keeps reporting the
pre-mutation `snapshot_id` (`total_tracks` does update). It's passed through here because
it's part of the API's response, not because it's a reliable version marker.

## Command reference

```
spotify auth                          # interactive login (human must run this themselves)
spotify auth status                   # confirm auth, see logged-in user
spotify auth logout

spotify search track "<query>" [--artist "<name>"] [--limit N]
spotify search artist "<query>"

spotify playlists                     # = playlist list
spotify playlist list
spotify playlist show "<name>" [--playlist-id ID]
spotify playlist create "<name>" [--public/--private] [--description "..."]
spotify playlist add "<track>" "<playlist>" [--artist "..."] [--track-uri URI] [--playlist-id ID] [--allow-duplicate] [--interactive] [--dry-run]
spotify playlist remove "<track>" "<playlist>" [--artist "..."] [--track-uri URI] [--playlist-id ID] [--dry-run]
spotify playlist add-album "<album>" "<playlist>" [--artist "..."] [--album-uri URI] [--playlist-id ID] [--allow-duplicate] [--interactive] [--dry-run]
spotify playlist import "<playlist>" <file> [--playlist-id ID] [--allow-duplicate] [--interactive] [--stop-on-error] [--dry-run]
spotify playlist dedupe "<playlist>" [--playlist-id ID] [--dry-run]

spotify library add "<track>"         # = liked add
spotify library remove "<track>"      # = liked remove
spotify library list [--limit N]      # = liked list

spotify queue "<track>" [--artist "..."] [--track-uri URI] [--device-id ID]
spotify devices
spotify now                           # what's currently playing/paused

spotify install-skill [--force]       # install the queue-song Claude Code skill to ~/.claude/skills
```

Always quote track, artist, album, and playlist names — they routinely contain spaces
and punctuation (`"Black Hole Sun"`, `"90s Alt Rock"`).

## Workflow: fulfilling a natural-language request

For something like *"find 15 songs similar to Alice in Chains and Soundgarden and add them
to my Grunge playlist, avoiding duplicates"*:

1. **You** (the agent) decide which specific songs are "similar" — this CLI has no
   recommendation endpoint (Spotify deprecated public access to Recommendations/Related
   Artists/Audio Features for apps like this one in Nov 2024; see README.md). Use your own
   knowledge to pick ~15 specific track/artist pairs.
2. Confirm the destination playlist exists and inspect its current contents:
   ```bash
   spotify --json playlist show "Grunge"
   ```
   If it doesn't exist yet, ask the user, or create it: `spotify --json playlist create "Grunge"`.
3. For each candidate song, search first rather than guessing a URI:
   ```bash
   spotify --json search track "Rooster" --artist "Alice in Chains"
   ```
   Inspect the results before adding — don't assume the first hit is right if the query
   was loose (e.g. a common song title).
4. Add each track. `playlist add` already checks the destination for an existing copy and
   skips it — you do not need to separately diff track lists yourself:
   ```bash
   spotify --json playlist add "Rooster" "Grunge" --artist "Alice in Chains"
   ```
   Exit code `0` with `"added": false, "reason": "duplicate"` in the JSON means it was
   already present and correctly skipped — that's success, not a failure to handle.
5. If a track search comes back ambiguous (exit code `3`), look at `candidates` in the
   JSON and either pick the best match by re-running with `--artist` set precisely, or use
   `--track-uri` if you already know the exact Spotify URI.
6. Summarize what was actually added/skipped back to the user — don't just report success;
   the per-track JSON tells you exactly what happened to each one.

### Shortcut for a known list: `playlist import`

Once you've decided on a fixed list of specific tracks (step 1 above, or any time the user
hands you an explicit list), you don't have to loop `playlist add` yourself — write the list
to a file (or pipe JSON via stdin) and let `playlist import` do the search-add-skip loop in
one call. This is preferable when the list is more than a couple of tracks: fewer commands,
and you get one JSON summary instead of parsing N separate results.

```bash
cat > /tmp/tracks.json <<'EOF'
[
  {"track": "Rooster", "artist": "Alice in Chains"},
  {"track": "Black Hole Sun", "artist": "Soundgarden"}
]
EOF
spotify --json playlist import "Grunge" /tmp/tracks.json
```

Or pipe it directly without a temp file:

```bash
echo '["Rooster", {"track": "Would?", "artist": "Alice in Chains"}]' | spotify --json playlist import "Grunge" -
```

The result JSON has a `results` array (one entry per input item, with a `status` of
`added`, `duplicate`, `would_add`, `not_found`, or `ambiguous`) and a `summary` with counts.
Exit code is still `0` even if some entries were skipped as `not_found`/`ambiguous` — check
`summary` rather than relying on the exit code to know whether everything landed, then
resolve any `not_found`/`ambiguous` entries individually with `playlist add` (using a more
precise `--artist` or `--track-uri`) if you want them added too.

## Rules for ambiguous or destructive operations

- **Never silently guess** on an ambiguous match. If the CLI returns exit code `3`
  (ambiguous) or `2` (not found), that is the CLI declining to guess for you — narrow the
  query (`--artist`, exact name) or ask the user, rather than picking whichever candidate
  looks plausible without stating your reasoning.
- **`--interactive` is for humans at a real terminal, not for you.** It prompts on stdin
  when a match is ambiguous, but that prompt only ever engages in an interactive TTY without
  `--json` — passing `--interactive` alongside `--json` (which you should always be doing)
  is simply ignored and the command falls back to returning `candidates` with exit code `3`,
  exactly as if the flag weren't there. So it's harmless to leave off, and pointless to add,
  in anything you invoke yourself.
- **Inspect before you mutate.** Before adding tracks in bulk or deduplicating, run
  `playlist show` (or rely on `playlist add`'s built-in duplicate check) so you know what's
  already there. `playlist add` and `playlist add-album` already skip tracks already
  present in the destination — you don't need to reimplement that check, just don't pass
  `--allow-duplicate` unless the user explicitly asked for duplicates.
- **Use `--dry-run` before a bulk or destructive change** you're not fully confident about
  — `playlist dedupe`, `playlist add-album`, or any `playlist add`/`playlist remove` a user
  hasn't explicitly confirmed. Show the user the dry-run result before re-running for real.
- **`playlist remove` removes every occurrence** of the matched track from the playlist
  (Spotify's current API has no per-position removal). If duplicates are wanted, avoid
  removing when only one instance should be removed — check `playlist show` first.
- **This tool never deletes a playlist**, by design — there is no `playlist delete`
  command. If asked to "delete a playlist," say this isn't supported and suggest
  unfollowing/archiving it manually in Spotify instead.
- **`spotify auth` requires a human's browser** — an agent cannot complete the OAuth
  consent screen. If a command fails with exit code `4`, stop and ask the user to run
  `spotify auth` themselves, then retry your command afterward.
- **`spotify queue` needs Spotify Premium and an active device.** If it fails with exit
  code `5`, read the message (it distinguishes "no active device" from "Premium
  required") and relay that to the user rather than retrying blindly — check
  `spotify devices` if you want to confirm device state first.

## Notes for shell scripting

- All commands are non-interactive and never read from stdin, so they're safe to call from
  a script or subprocess without a TTY.
- `playlist create` defaults to a **public** playlist; pass `--private` if that's not
  wanted.
- Names are matched case-insensitively; an exact (trimmed, case-insensitive) name match is
  preferred over a substring match, and either one is only auto-selected when it's unique —
  otherwise you get exit code `3` with candidates.
