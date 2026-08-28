"""Pure, network-free matching logic: picking a track among search results, resolving a
playlist name to one playlist, and planning a duplicate-removal pass. Kept dependency-free
and side-effect-free so it can be unit tested without hitting Spotify.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from .errors import AmbiguousMatchError, NotFoundError
from .models import Playlist, Track


def _norm(s: str) -> str:
    return " ".join(s.lower().strip().split())


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


@dataclass
class ScoredTrack:
    track: Track
    score: float


def score_tracks(tracks: list[Track], title_query: str, artist_query: str | None) -> list[ScoredTrack]:
    scored: list[ScoredTrack] = []
    for t in tracks:
        title_score = 1.0 if _norm(t.name) == _norm(title_query) else _similarity(t.name, title_query)
        if artist_query:
            artist_score = 1.0 if any(_norm(a) == _norm(artist_query) for a in t.artists) else max(
                (_similarity(a, artist_query) for a in t.artists), default=0.0
            )
            combined = 0.6 * title_score + 0.4 * artist_score
        else:
            combined = title_score
        scored.append(ScoredTrack(t, combined))
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored


def pick_best_track(
    tracks: list[Track],
    title_query: str,
    artist_query: str | None,
    *,
    auto_threshold: float = 0.92,
    gap_threshold: float = 0.08,
) -> Track:
    """Auto-selects a track only when it's a near-exact match with a clear margin over
    the runner-up; otherwise raises AmbiguousMatchError with ranked candidates so the
    caller (human or agent) can disambiguate rather than the CLI guessing silently.
    """
    if not tracks:
        suffix = f" by '{artist_query}'" if artist_query else ""
        raise NotFoundError(f"No tracks found matching '{title_query}'{suffix}.")

    scored = score_tracks(tracks, title_query, artist_query)
    best = scored[0]
    second = scored[1] if len(scored) > 1 else None

    if best.score >= auto_threshold and (second is None or best.score - second.score >= gap_threshold):
        return best.track

    suffix = f" by '{artist_query}'" if artist_query else ""
    raise AmbiguousMatchError(
        f"Multiple plausible matches for '{title_query}'{suffix} — pass --artist to narrow it down, "
        "or --track-uri with an exact Spotify track URI.",
        candidates=[{"score": round(s.score, 3), **s.track.to_dict()} for s in scored[:8]],
    )


def resolve_playlist(playlists: list[Playlist], query: str) -> Playlist:
    """Resolves a playlist name to exactly one playlist, preferring exact (case-insensitive)
    name matches over substring matches, and raising AmbiguousMatchError rather than guessing
    when multiple playlists share a name.
    """
    norm_q = _norm(query)

    exact = [p for p in playlists if _norm(p.name) == norm_q]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise AmbiguousMatchError(
            f"Multiple playlists are named '{query}'. Use --playlist-id to disambiguate.",
            candidates=[p.to_dict() for p in exact],
        )

    partial = [p for p in playlists if norm_q in _norm(p.name)]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise AmbiguousMatchError(
            f"Multiple playlists match '{query}'. Use --playlist-id to disambiguate, or pass the exact name.",
            candidates=[p.to_dict() for p in partial],
        )

    raise NotFoundError(f"No playlist found matching '{query}'. Run 'spotify playlists' to list them.")


def dedupe_plan(uris_in_order: list[str]) -> dict:
    """Computes which URIs occur more than once in a playlist. Because the current Remove
    Playlist Items API removes *all* occurrences of a given URI (there is no per-position
    removal any more), the only non-brittle way to deduplicate is: remove every duplicated
    URI entirely, then re-add each one exactly once. That collapses duplicates to a single
    occurrence but — as a documented tradeoff, not a hidden one — moves those tracks to the
    end of the playlist rather than preserving their original position.
    """
    seen: set[str] = set()
    duplicate_uris: list[str] = []
    for u in uris_in_order:
        if u in seen and u not in duplicate_uris:
            duplicate_uris.append(u)
        seen.add(u)

    unique_count = len(dict.fromkeys(uris_in_order))
    return {
        "duplicate_uris": duplicate_uris,
        "total_items": len(uris_in_order),
        "unique_items": unique_count,
        "removed_count": len(uris_in_order) - unique_count,
    }
