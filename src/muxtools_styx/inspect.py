from __future__ import annotations

from pathlib import Path
from typing import Any

from muxtools import ParsedFile, TrackType

from . import _anitomy
from .audio import track_bitrate


def inspect_file(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"media file does not exist: {resolved}")
    elements = _anitomy.parse(resolved.name)
    media = ParsedFile.from_file(resolved, inspect_file)

    def track_data(kind: TrackType) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for track in media.find_tracks(type=kind):
            result.append(
                {
                    "index": track.relative_index,
                    "language": track.sanitized_lang.to_tag(),
                    "codec": track.codec_name,
                    "bitrate": track_bitrate(track),
                    "title": track.title,
                    "default": track.is_default,
                    "forced": track.is_forced,
                }
            )
        return result

    return {
        "file": str(resolved),
        "elements": [{"kind": element.kind.name, "value": element.value, "position": element.position} for element in elements],
        "video": track_data(TrackType.VIDEO),
        "audio": track_data(TrackType.AUDIO),
        "subtitles": track_data(TrackType.SUB),
    }


def format_inspection(data: dict[str, Any]) -> str:
    lines = [str(data["file"]), "Filename elements:"]
    lines.extend(f"  {item['position']:>4}  {item['kind']}: {item['value']}" for item in data["elements"])
    for label in ("video", "audio", "subtitles"):
        lines.append(f"{label.title()} tracks:")
        tracks = data[label]
        if not tracks:
            lines.append("  (none)")
            continue
        for track in tracks:
            bitrate = f", {track['bitrate']} bps" if track["bitrate"] is not None else ""
            title = f", {track['title']}" if track["title"] else ""
            flags = ", ".join(flag for flag in ("default" if track["default"] else "", "forced" if track["forced"] else "") if flag)
            suffix = f", {flags}" if flags else ""
            lines.append(f"  {track['index']}: {track['language']}, {track['codec']}{bitrate}{title}{suffix}")
    return "\n".join(lines)
