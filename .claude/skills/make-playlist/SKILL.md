---
name: make-playlist
description: >
  Build or fill a Spotify playlist via the spotify-cli. Trigger: "make me a playlist
  of X", "create a playlist called Y", "add 20 songs like Z to my Driving playlist",
  "build a workout mix", "put some 90s grunge in Grunge", or any request to create a
  playlist or add a batch of tracks to one. Picks the actual songs itself — Spotify has
  no recommendation API. Does not require Premium.
---

# Make a Playlist

Create a playlist and fill it with tracks using the `spotify` CLI (installed via
`pip install spotify-cli` or `pip install -e .` from the SpotifyHelper repo, and
expected to be on `PATH`). Full command reference and exit-code contract are documented
in that project's `AGENTS.md` — read it if any step here is unclear.

**You choose the songs.** The CLI has no recommendation endpoint — Spotify deprecated
public access to Recommendations / Related Artists / Audio Features in November 2024.
When the user describes a vibe, genre, era, or seed artist rather than naming tracks,
pick specific track/artist pairs from your own knowledge. Don't ask the user to supply
the list unless they clearly want to.

## Steps

1. **Decide the track list.** Aim for the count the user asked for (default to ~15–20 if
   they didn't say). Each entry needs a title and, wherever you know it, an artist —
   `--artist` is what keeps a common title from coming back ambiguous.

2. **Find or create the destination playlist.**
   ```bash
   spotify --json playlist show "<playlist>"
   ```
   - `0` — it exists. The response includes its current `tracks`, so you can see what's
     already there and avoid proposing songs it already has.
   - `2` (not found) — it doesn't exist. If the user's request assumed it already
     existed ("add these to my Grunge playlist"), the name may be a typo — run
     `spotify --json playlists` and confirm with them before creating a second one.
     Otherwise create it:
     ```bash
     spotify --json playlist create "<playlist>" --private
     ```
     Add `--description "..."` if the request suggests one.

     **Visibility can't be set through the API.** `playlist create` defaults to public
     and Spotify does not reliably honor `--private` on creation, so keep passing
     `--private` (harmless, and correct if Spotify ever fixes it) but assume the new
     playlist may be public regardless. The `public` field in the response is not
     trustworthy either way — don't quote it back to the user as fact. If they wanted a
     private playlist, tell them to flip it themselves in the Spotify app
     (playlist → ⋯ → Make private); there is no way to do it from this CLI.
   - `3` (ambiguous) — several playlists match that name. Show the user the `candidates`
     and ask which they meant, or re-run `playlist show` with `--playlist-id <id>`.

3. **Add the tracks in one call** with `playlist import`, piping the list on stdin —
   don't loop `playlist add` for more than a couple of tracks:
   ```bash
   echo '[{"track":"Rooster","artist":"Alice in Chains"},{"track":"Black Hole Sun","artist":"Soundgarden"}]' \
     | spotify --json playlist import "<playlist>" -
   ```
   Use `--playlist-id <id>` instead of the name if you resolved an ambiguity in step 2.
   For a single track, `spotify --json playlist add "<track>" "<playlist>" --artist "<artist>"`
   is fine.

4. **Read the `summary`, not the exit code.** `playlist import` exits `0` even when some
   entries didn't land. The result has one `results` entry per input, each with a
   `status` of `added`, `duplicate`, `would_add`, `not_found`, or `ambiguous`, plus a
   `summary` with counts. Anything other than `added`/`duplicate` means that song is
   **not** in the playlist yet.

5. **Resolve the leftovers.** For each `not_found` or `ambiguous` entry, retry it
   individually:
   ```bash
   spotify --json search track "<track>" --artist "<artist>"
   spotify --json playlist add "<track>" "<playlist>" --track-uri <uri>
   ```
   An `ambiguous` entry carries its own `candidates` — pick the right one and pin it with
   `--track-uri`. If a song genuinely isn't on Spotify, pick a different one rather than
   leaving the playlist short, and say what you substituted.

6. **Report what actually happened**: the playlist name, whether you created it, how
   many tracks were added, and anything skipped as a duplicate or swapped out. Don't
   report a bare "done" — the per-track results tell you exactly what landed. Don't
   state the playlist's visibility; if you created one and the user wanted it private,
   add the manual "make it private in the app" step instead.

## Handling exit codes

- `0` — success (but for `import`, still check `summary`, per step 4).
- `2` (not found) — a playlist or track name didn't match. Create the playlist, or search
  with a looser query, then retry.
- `3` (ambiguous) — read `candidates` and pin the choice with `--track-uri`,
  `--playlist-id`, or a precise `--artist`. Don't just take the first candidate silently.
- `4` (not authenticated) — tell the user to run `spotify auth` themselves; it needs
  their browser and you cannot do it for them.
- `5` (API error) — relay the message (rate limit, etc.); usually not fixable by an
  immediate retry.

## Notes

- `playlist add`, `add-album`, and `import` already skip tracks already present in the
  destination. Don't pass `--allow-duplicate` unless the user explicitly wants duplicates,
  and don't diff the track lists yourself.
- Use `--dry-run` first for a bulk change the user hasn't explicitly confirmed (and
  always before `playlist dedupe`), then show them the preview before re-running for real.
- Adding a whole album is one call: `spotify --json playlist add-album "<album>" "<playlist>" --artist "<artist>"`.
- Don't pass `--interactive`; it's a no-op with `--json` (see AGENTS.md).
- **There is no `playlist delete`**, by design. If asked to delete a playlist, say it
  isn't supported and suggest unfollowing it in the Spotify app instead. `playlist remove`
  removes *every* occurrence of a matched track.
- Ignore `snapshot_id` — Spotify's read endpoints serve a stale value, so it's not a
  usable version marker.
- If `spotify` isn't found on `PATH`, tell the user the CLI isn't installed (or not on
  `PATH`) on this machine — don't guess at an install path.
