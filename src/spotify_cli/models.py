"""Small, dependency-free data models for the pieces of the Spotify API this CLI uses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Track:
    id: str
    uri: str
    name: str
    artists: list[str]
    album: str | None = None
    duration_ms: int | None = None

    @classmethod
    def from_api(cls, obj: dict) -> "Track":
        return cls(
            id=obj["id"],
            uri=obj["uri"],
            name=obj["name"],
            artists=[a["name"] for a in obj.get("artists", [])],
            album=(obj.get("album") or {}).get("name"),
            duration_ms=obj.get("duration_ms"),
        )

    @property
    def artist_str(self) -> str:
        return ", ".join(self.artists)

    @property
    def label(self) -> str:
        return f'"{self.name}" — {self.artist_str}' if self.artists else f'"{self.name}"'

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "uri": self.uri,
            "name": self.name,
            "artists": self.artists,
            "album": self.album,
            "duration_ms": self.duration_ms,
        }


@dataclass
class Playlist:
    id: str
    uri: str
    name: str
    owner: str
    public: bool | None
    collaborative: bool
    total_tracks: int
    snapshot_id: str

    @classmethod
    def from_api(cls, obj: dict) -> "Playlist":
        owner_obj = obj.get("owner") or {}
        return cls(
            id=obj["id"],
            uri=obj.get("uri", f"spotify:playlist:{obj['id']}"),
            name=obj["name"],
            owner=owner_obj.get("display_name") or owner_obj.get("id", "?"),
            public=obj.get("public"),
            collaborative=obj.get("collaborative", False),
            total_tracks=(obj.get("tracks") or {}).get("total", 0),
            snapshot_id=obj.get("snapshot_id", ""),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "uri": self.uri,
            "name": self.name,
            "owner": self.owner,
            "public": self.public,
            "collaborative": self.collaborative,
            "total_tracks": self.total_tracks,
            "snapshot_id": self.snapshot_id,
        }


@dataclass
class Device:
    id: str | None
    name: str
    type: str
    is_active: bool

    @classmethod
    def from_api(cls, obj: dict) -> "Device":
        return cls(
            id=obj.get("id"),
            name=obj.get("name", "?"),
            type=obj.get("type", "?"),
            is_active=obj.get("is_active", False),
        )

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "type": self.type, "is_active": self.is_active}
