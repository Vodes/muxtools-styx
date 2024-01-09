from argparse import Namespace
from pathlib import Path
from pymediainfo import Track

from muxtools import Premux, get_track_list, TrackType, find_tracks, mux, SubTrack, Setup, SubFile, CABIN_PRESET, FontFile, warn
from muxtools.muxing.tracks import _track

__all__ = [
    "basic_mux",
    "single_file_mux",
]


def get_sync_args(f: Path, sync: int, tracks: int | list[int], type: TrackType) -> list[str]:
    if tracks == -1:
        tracks = [track.track_id for track in find_tracks(f, type=type)]
    args = list[str]()
    for tr in tracks:
        args.extend(["--sync", f"{tr}:{sync}"])
    return args


def is_lang(track: Track, lang: str) -> bool:
    languages: list[str] = getattr(track, "other_language", None) or list[str]()
    return bool([l for l in languages if l.casefold() == lang.casefold()])


def basic_mux(input1: Path, input2: Path, args: Namespace) -> Path:
    subs_to_keep = -1 if args.keep_subs else None
    if args.keep_non_english:
        non_english = find_tracks(input1, lang="eng", reverse_lang=True, type=TrackType.SUB)
        subs_to_keep = None if not non_english else non_english

    sync_args = ["--no-global-tags"]
    if args.sub_sync or args.audio_sync:
        if args.sub_sync and subs_to_keep != None:
            absolute = [int(track.track_id) for track in subs_to_keep] if isinstance(subs_to_keep, list) else subs_to_keep
            sync_args.extend(get_sync_args(input1, args.sub_sync, absolute, TrackType.SUB))
        if args.audio_sync and args.keep_audio:
            sync_args.extend(get_sync_args(input1, args.audio_sync, -1, TrackType.AUDIO))

    subs_to_keep = subs_to_keep if not isinstance(subs_to_keep, list) else [int(track.relative_id) for track in subs_to_keep]
    mkv1 = Premux(input1, -1 if args.keep_video else None, -1 if args.keep_audio else None, subs_to_keep, subs_to_keep != None, sync_args)
    mkv2 = Premux(
        input2,
        None if args.keep_video else -1,
        subtitles=None if args.discard_new_subs else -1,
        keep_attachments=not args.discard_new_subs,
    )
    return Path(mux(mkv1, mkv2, outfile=args.output, quiet=not args.verbose))


def single_file_mux(input1: Path, args: Namespace) -> Path:
    Setup("Temp", None, clean_work_dirs=True)
    subtracks = list[tuple[SubFile, Track]]()
    fonts = list[FontFile]()
    all_subs = find_tracks(input1, type=TrackType.SUB)
    to_process = [tr for tr in all_subs if bool([lan for lan in args.sub_languages if is_lang(tr, lan)])]
    other_subs = [tr for tr in all_subs if tr not in to_process]

    for pr in to_process:
        sub = SubFile.from_mkv(input1, pr.relative_id)
        if args.tpp_subs:
            warn("TPP not implemented yet...", sleep=1)
        if args.restyle_subs:
            sub = sub.unfuck_cr(alt_styles=["overlap"]).purge_macrons().restyle(CABIN_PRESET)
        fonts = sub.collect_fonts()
        subtracks.append((sub, pr))

    processed_tracks = [st.to_track(tr.title, tr.lang, str(tr.default).lower() == "yes", str(tr.forced).lower() == "yes") for (st, tr) in subtracks]
    final_tracks = [Premux(input1, subtitles=None, keep_attachments=False), *processed_tracks]
    if other_subs:
        final_tracks.append(Premux(input1, video=None, audio=None, subtitles=[tr.relative_id for tr in other_subs]))
    final_tracks.extend(fonts)
    return Path(mux(*final_tracks, outfile=args.output, quiet=not args.verbose, print_cli=True))


def advanced_mux(input1: Path, input2: Path, args: Namespace) -> Path:
    ...
