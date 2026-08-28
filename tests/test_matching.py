import pytest

from spotify_cli.errors import AmbiguousMatchError, NotFoundError
from spotify_cli.matching import dedupe_plan, pick_best_track, resolve_playlist
from spotify_cli.models import Playlist, Track


def make_track(name, artists, id_="id1"):
    return Track(id=id_, uri=f"spotify:track:{id_}", name=name, artists=artists, album="Album", duration_ms=1000)


def make_playlist(name, id_="p1"):
    return Playlist(id=id_, uri=f"spotify:playlist:{id_}", name=name, owner="me", public=True, collaborative=False, total_tracks=0, snapshot_id="s1")


class TestPickBestTrack:
    def test_exact_title_and_artist_auto_selected(self):
        tracks = [
            make_track("Black Hole Sun", ["Soundgarden"], "a"),
            make_track("Black Hole Sun - Live", ["Soundgarden"], "b"),
        ]
        picked = pick_best_track(tracks, "Black Hole Sun", "Soundgarden")
        assert picked.id == "a"

    def test_exact_title_no_artist_given_auto_selected(self):
        tracks = [make_track("Black Hole Sun", ["Soundgarden"], "a")]
        picked = pick_best_track(tracks, "Black Hole Sun", None)
        assert picked.id == "a"

    def test_ambiguous_when_close_scores(self):
        tracks = [
            make_track("Rooster", ["Alice in Chains"], "a"),
            make_track("Rooster", ["Some Cover Band"], "b"),
        ]
        with pytest.raises(AmbiguousMatchError) as exc:
            pick_best_track(tracks, "Rooster", None)
        assert len(exc.value.candidates) == 2

    def test_no_results_raises_not_found(self):
        with pytest.raises(NotFoundError):
            pick_best_track([], "Nonexistent Song", None)

    def test_artist_mismatch_prevents_auto_select(self):
        tracks = [
            make_track("Would?", ["Alice in Chains"], "a"),
            make_track("Would?", ["Cover Band"], "b"),
        ]
        picked = pick_best_track(tracks, "Would?", "Alice in Chains")
        assert picked.id == "a"


class TestResolvePlaylist:
    def test_exact_match_wins_over_substring(self):
        playlists = [make_playlist("Driving", "p1"), make_playlist("Driving Long", "p2")]
        resolved = resolve_playlist(playlists, "Driving")
        assert resolved.id == "p1"

    def test_case_insensitive_exact_match(self):
        playlists = [make_playlist("Driving", "p1")]
        resolved = resolve_playlist(playlists, "driving")
        assert resolved.id == "p1"

    def test_unique_substring_match(self):
        playlists = [make_playlist("90s Alt Rock", "p1"), make_playlist("Workout", "p2")]
        resolved = resolve_playlist(playlists, "alt rock")
        assert resolved.id == "p1"

    def test_ambiguous_duplicate_names(self):
        playlists = [make_playlist("Driving", "p1"), make_playlist("Driving", "p2")]
        with pytest.raises(AmbiguousMatchError) as exc:
            resolve_playlist(playlists, "Driving")
        assert len(exc.value.candidates) == 2

    def test_not_found(self):
        playlists = [make_playlist("Driving", "p1")]
        with pytest.raises(NotFoundError):
            resolve_playlist(playlists, "Nonexistent Playlist Name")


class TestDedupePlan:
    def test_no_duplicates(self):
        plan = dedupe_plan(["a", "b", "c"])
        assert plan["removed_count"] == 0
        assert plan["duplicate_uris"] == []

    def test_simple_duplicates(self):
        plan = dedupe_plan(["a", "b", "a", "c", "b", "b"])
        assert set(plan["duplicate_uris"]) == {"a", "b"}
        assert plan["total_items"] == 6
        assert plan["unique_items"] == 3
        assert plan["removed_count"] == 3

    def test_empty_playlist(self):
        plan = dedupe_plan([])
        assert plan["removed_count"] == 0
        assert plan["duplicate_uris"] == []
