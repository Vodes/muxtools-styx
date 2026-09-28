from __future__ import annotations

from .selection import SelectedTrack


def sync_arguments(tracks: list[SelectedTrack], delay: int) -> list[str]:
    if not delay:
        return []
    args: list[str] = []
    for selected in tracks:
        args.extend(("--sync", f"{selected.track.index}:{delay}"))
    return args
