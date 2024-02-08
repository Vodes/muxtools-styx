from pathlib import Path

from pymediainfo import Track
from muxtools import find_tracks, TrackType, get_executable, info, debug, error, run_commandline
from .muxing import is_lang
from shlex import join


def fix_tags(fil: Path):
    mkvpropedit = get_executable("mkvpropedit", False)
    english_sub_tracks = find_tracks(fil, lang="en", type=TrackType.SUB)
    japanese_sub_tracks = find_tracks(fil, lang="jp", type=TrackType.SUB)
    otherNonJP = find_tracks(fil, lang="jp", reverse_lang=True, type=TrackType.SUB)
    otherNonJP = [track for track in otherNonJP if track.relative_id not in [track.relative_id for track in english_sub_tracks]]
    audio_tracks = find_tracks(fil, type=TrackType.AUDIO)

    full_sub = [set_english(track) for track in english_sub_tracks if is_likely_full_en(track)]
    if not full_sub:
        full_sub = [set_english(track) for track in japanese_sub_tracks if is_likely_full_en(track)]

    signs = [track for track in otherNonJP if is_likely_sign(track)]
    signs.extend([track for track in english_sub_tracks if is_likely_sign(track)])

    commands = [mkvpropedit, str(fil.resolve())]
    for index, sub in enumerate(full_sub):
        print(f"Full en sub: {sub.title}")
        commands.extend(["--edit", f"track:{sub.track_id + 1}"])
        commands.extend(["--set", f"language={sub.language}"])
        commands.extend(["--set", "flag-forced=0", "--set", f"flag-default={1 if index == 0 else 0}"])

    for sub in signs:
        print(f"Some signs track: {sub.title}")
        commands.extend(["--edit", f"track:{sub.track_id + 1}"])
        commands.extend(["--set", "flag-forced=1", "--set", f"flag-default=0"])

    for sub in [track for track in otherNonJP if track.relative_id not in [track.relative_id for track in signs]]:
        print(f"Full sub other languages: {sub.title}")
        commands.extend(["--edit", f"track:{sub.track_id + 1}"])
        commands.extend(["--set", "flag-forced=0", "--set", f"flag-default=1"])

    for audio in audio_tracks:
        print(f"Audio: {audio.title}")
        commands.extend(["--edit", f"track:{audio.track_id + 1}"])
        commands.extend(["--set", "flag-forced=0", "--set", f"flag-default=1"])

    run_commandline(commands)


def set_english(track: Track) -> Track:
    track.language = "en"
    return track


def is_likely_full_en(track: Track) -> bool:
    isenglish = is_lang(track, "en") or is_lang(track, "jp")
    hasForced = str(track.forced).lower() == "yes"
    title = str(track.title).lower()
    contains_sign_song = "sign" in title or "song" in title or "force" in title

    if isenglish:
        return not hasForced and not contains_sign_song


def is_likely_sign(track: Track) -> bool:
    hasForced = str(track.forced).lower() == "yes"
    title = str(track.title).lower()
    contains_sign_song = "sign" in title or "song" in title or "force" in title

    return hasForced or contains_sign_song
