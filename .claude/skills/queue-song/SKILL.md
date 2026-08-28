---
name: queue-song
description: >
  Add a song to the user's Spotify playback queue via the spotify-cli. Trigger:
  "queue this song", "add X to the queue", "play X next", "queue up a track",
  "queue something like what's playing", or any request to queue a specific,
  freely-chosen, or currently-playing-based song. Requires Spotify Premium and
  an actively playing device.
---

# Queue a Song

Add a track to Spotify's playback queue using the `spotify` CLI in this repo
(activate `.venv` first: `source .venv/bin/activate`). Full command reference
and exit-code contract are in `AGENTS.md` at the repo root — read it if any
step here is unclear.

## Steps

1. If the user didn't name a specific song, pick one yourself — no need to ask.
   - If the request is based on what's currently playing (e.g. "queue something
     like this", "add another song by whoever this is"), run `spotify --json now`
     first to find out what's playing, then pick a song using that track/artist
     as the basis. If `playing` is `false` (nothing playing) or `type` isn't
     `"track"` (an ad or podcast episode), tell the user there's no current
     track to go on and ask what they'd like queued instead.
2. Queue it directly; `spotify queue` resolves the track internally, no separate
   search step needed for an unambiguous title:
   ```bash
   spotify --json queue "<track>" --artist "<artist>"
   ```
3. Handle the result by exit code:
   - `0` — success. Report the track (name, artist, album) that was queued.
   - `2` (not found) — run `spotify --json search track "<track>" --artist "<artist>"`
     with a looser query, then retry with the right title/artist or `--track-uri`.
   - `3` (ambiguous) — inspect `candidates` in the JSON, pick the best match
     yourself (or ask the user if genuinely unclear), and retry with
     `--track-uri <uri>` pinned to that candidate.
   - `4` (not authenticated) — tell the user to run `spotify auth` themselves
     (requires their browser); you cannot do this for them.
   - `5` (API error) — read the message: either "no active device" (tell the
     user to start playback on a device — run `spotify --json devices` to show
     what's available) or "Premium required" (not fixable, just relay it).

## Notes

- Don't pass `--interactive`; it's a no-op with `--json` (see AGENTS.md).
- No need to check `spotify auth status` or `spotify devices` up front —
  just try the queue call and handle exit codes 4/5 if they occur.
