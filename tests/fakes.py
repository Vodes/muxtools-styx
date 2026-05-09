from __future__ import annotations

from dataclasses import dataclass

from muxtools import TrackType


@dataclass(frozen=True, slots=True)
class FakeTrack:
    index: int
    relative_index: int
    type: TrackType
    codec_name: str
    language: str | None = None
    title: str | None = None
    is_default: bool = True
    is_forced: bool = False
    codec_long_name: str | None = None
    container_delay: int = 0
    bit_rate: int | None = None
