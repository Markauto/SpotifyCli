import pytest

from spotify_cli.errors import ConfigError
from spotify_cli.track_list import parse_json_track_list, parse_text_track_list


class TestParseTextTrackList:
    def test_plain_titles(self):
        entries = parse_text_track_list("Black Hole Sun\nWould?\n")
        assert [e.query for e in entries] == ["Black Hole Sun", "Would?"]
        assert all(e.artist is None and e.uri is None for e in entries)

    def test_title_and_artist(self):
        entries = parse_text_track_list("Black Hole Sun | Soundgarden\n")
        assert entries[0].query == "Black Hole Sun"
        assert entries[0].artist == "Soundgarden"

    def test_comments_and_blank_lines_ignored(self):
        text = "# comment\n\nBlack Hole Sun | Soundgarden\n   \n# another\nWould?\n"
        entries = parse_text_track_list(text)
        assert len(entries) == 2

    def test_spotify_uri_line_used_directly(self):
        entries = parse_text_track_list("spotify:track:4iV5W9uYEdYUVa79Axb7Rh\n")
        assert entries[0].uri == "spotify:track:4iV5W9uYEdYUVa79Axb7Rh"
        assert entries[0].query is None

    def test_spotify_url_line_converted_to_uri(self):
        entries = parse_text_track_list("https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh?si=abc\n")
        assert entries[0].uri == "spotify:track:4iV5W9uYEdYUVa79Axb7Rh"

    def test_pipe_with_empty_title_raises(self):
        with pytest.raises(ConfigError):
            parse_text_track_list(" | Soundgarden\n")

    def test_pasted_list_with_timestamps_stripped_by_user(self):
        # realistic paste, cleaned up: title | artist per line
        text = (
            "I Fall in Love Too Easily | Caleb Belkin\n"
            "New Slang | The Shins\n"
            "Teardrop | Massive Attack\n"
        )
        entries = parse_text_track_list(text)
        assert len(entries) == 3
        assert entries[1].query == "New Slang"
        assert entries[1].artist == "The Shins"


class TestParseJsonTrackList:
    def test_array_of_strings(self):
        entries = parse_json_track_list('["Black Hole Sun", "Would?"]')
        assert [e.query for e in entries] == ["Black Hole Sun", "Would?"]

    def test_array_of_objects(self):
        entries = parse_json_track_list(
            '[{"track": "Black Hole Sun", "artist": "Soundgarden"}, {"uri": "spotify:track:abc123"}]'
        )
        assert entries[0].query == "Black Hole Sun"
        assert entries[0].artist == "Soundgarden"
        assert entries[1].uri == "spotify:track:abc123"

    def test_title_key_also_accepted(self):
        entries = parse_json_track_list('[{"title": "Would?", "artist": "Alice in Chains"}]')
        assert entries[0].query == "Would?"

    def test_invalid_json_raises_config_error(self):
        with pytest.raises(ConfigError):
            parse_json_track_list("not json")

    def test_non_array_top_level_raises(self):
        with pytest.raises(ConfigError):
            parse_json_track_list('{"track": "Would?"}')

    def test_object_missing_track_and_uri_raises(self):
        with pytest.raises(ConfigError):
            parse_json_track_list('[{"artist": "Soundgarden"}]')
