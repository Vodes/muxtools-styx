from __future__ import annotations

from .selection import SelectedTrack, mkvmerge_track_id


def sync_arguments(tracks: list[SelectedTrack], delay: int) -> list[str]:
    if not delay:
        return []
    args: list[str] = []
    for selected in tracks:
        args.extend(("--sync", f"{mkvmerge_track_id(selected.track)}:{delay}"))
    return args
