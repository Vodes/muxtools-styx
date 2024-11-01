from argparse import Namespace
from pathlib import Path
from pymediainfo import Track

from muxtools import (
    Premux,
    TrackType,
    find_tracks,
    mux,
    Setup,
    SubFile,
    GJM_GANDHI_PRESET,
    FontFile,
    warn,
    edit_style,
    gandhi_default,
)
from muxtools.subtitle.sub import LINES

__all__ = [
    "basic_mux",
    "advanced_mux",
]


def get_sync_args(f: Path, sync: int, tracks: int | list[int], type: TrackType) -> list[str]:
    if tracks == -1:
        tracks = [track.track_id for track in find_tracks(f, type=type)]
    args = list[str]()
    for tr in tracks:
        args.extend(["--sync", f"{tr}:{sync}"])
    return args


def is_lang(track: Track, lang: str | None) -> bool:
    languages: list[str] = getattr(track, "other_language", None) or list[str]()
    if (track.language == None or not languages) and lang == None:
        return True
    return bool([l for l in languages if l.casefold() == lang.casefold()])


def basic_mux(input1: Path, input2: Path, args: Namespace, output: Path) -> Path:
    subs_to_keep = -1 if args.keep_subs else None
    if args.keep_non_english:
        non_english = find_tracks(input1, lang="eng", reverse_lang=True, type=TrackType.SUB)
        subs_to_keep = None if not non_english else non_english

    if find_tracks(input2, lang="jpn", type=TrackType.AUDIO):
        audio_to_keep = find_tracks(input1, lang="jpn", reverse_lang=True, type=TrackType.AUDIO) if args.keep_audio else None
    else:
        audio_to_keep = find_tracks(input1, type=TrackType.AUDIO) if args.keep_audio else None

    sync_args = ["--no-global-tags"]
    if args.sub_sync or args.audio_sync:
        if args.sub_sync and subs_to_keep != None:
            absolute = [int(track.track_id) for track in subs_to_keep] if isinstance(subs_to_keep, list) else subs_to_keep
            sync_args.extend(get_sync_args(input1, args.sub_sync, absolute, TrackType.SUB))
        if args.audio_sync and audio_to_keep:
            absolute = [int(track.track_id) for track in audio_to_keep]
            sync_args.extend(get_sync_args(input1, args.audio_sync, absolute, TrackType.AUDIO))

    subs_to_keep = subs_to_keep if not isinstance(subs_to_keep, list) else [int(track.relative_id) for track in subs_to_keep]

    if not audio_to_keep:
        audio_to_keep = None
    else:
        languages = set([track.language for track in audio_to_keep])
        for lang in languages:
            subs = find_tracks(input1, lang=lang, type=TrackType.SUB)
            subs = [sub for sub in subs if is_likely_sign(sub)]
            if not subs:
                continue

            if not isinstance(subs_to_keep, list):
                subs_to_keep = []
            subs_to_keep.extend([int(sub.relative_id) for sub in subs if sub.relative_id not in subs_to_keep])

    audio_to_keep = audio_to_keep if not isinstance(audio_to_keep, list) else [int(track.relative_id) for track in audio_to_keep]
    mkv1 = Premux(input1, -1 if args.keep_video else None, audio_to_keep, subs_to_keep, subs_to_keep != None, sync_args)
    mkv2 = Premux(
        input2,
        None if args.keep_video else -1,
        subtitles=None if args.discard_new_subs else -1,
        keep_attachments=not args.discard_new_subs,
    )
    return Path(mux(mkv1, mkv2, outfile=output, quiet=not args.verbose))


def advanced_mux(input1: Path, args: Namespace, input2: Path | None = None) -> Path:
    Setup("Temp", None, clean_work_dirs=True)
    subtracks = list[tuple[SubFile, Track]]()
    fonts = list[FontFile]()
    all_subs = find_tracks(input1, type=TrackType.SUB)
    to_process = [tr for tr in all_subs if bool([lan for lan in args.sub_languages if is_lang(tr, lan)]) and (args.tpp_subs or args.restyle_subs)]
    other_subs = [tr for tr in all_subs if tr not in to_process]

    for pr in to_process:
        sub = SubFile.from_mkv(input1, pr.relative_id)
        if args.tpp_subs:
            warn("TPP not implemented yet...", sleep=1)
        if args.restyle_subs:
            preset = GJM_GANDHI_PRESET
            preset.append(edit_style(gandhi_default, "Sign"))
            preset.append(edit_style(gandhi_default, "Subtitle"))
            preset.append(edit_style(gandhi_default, "Subtitle-3", fontsize=66))
            sub = (
                sub.unfuck_cr(alt_styles=["overlap", "subtitle-2"], dialogue_styles=["main", "default", "narrator", "narration", "subtitle", "bd dx"])
                .purge_macrons()
                .restyle(preset)
            )
            replace_unknown_with_default(sub)

        fonts = sub.collect_fonts()
        subtracks.append((sub, pr))

    processed_tracks = [
        st.to_track(tr.title, tr.language, str(tr.default).lower() == "yes", str(tr.forced).lower() == "yes") for (st, tr) in subtracks
    ]
    final_tracks = [Premux(input1, subtitles=None, keep_attachments=False)]
    if args.best_audio and input2:
        non_jp_audio = find_tracks(input1, lang="jpn", type=TrackType.AUDIO, reverse_lang=True)
        jp_audio1 = find_tracks(input1, lang="jpn", type=TrackType.AUDIO)
        jp_audio2 = find_tracks(input2, lang="jpn", type=TrackType.AUDIO)
        if jp_audio1 and jp_audio2:
            final_tracks = [
                Premux(input1, audio=None if not non_jp_audio else [tr.relative_id for tr in non_jp_audio], subtitles=None, keep_attachments=False)
            ]
            jp_audio1 = jp_audio1[0]
            jp_audio2 = jp_audio2[0]
            jp_audio = (
                (input1, jp_audio1)
                if int(jp_audio1.bit_rate or jp_audio1.fromstats_bitrate) > int(jp_audio2.bit_rate or jp_audio2.fromstats_bitrate)
                else (input2, jp_audio2)
            )
            final_tracks.append(Premux(jp_audio[0], video=None, subtitles=None, keep_attachments=False, audio=jp_audio[1].relative_id))

    final_tracks.extend(processed_tracks)
    final_tracks.append(Premux(input1, video=None, audio=None, subtitles=[tr.relative_id for tr in other_subs] if other_subs else None))
    final_tracks.extend(fonts)
    return Path(mux(*final_tracks, outfile=args.output, quiet=not args.verbose))


def is_likely_sign(track: Track) -> bool:
    hasForced = str(track.forced).lower() == "yes"
    isDefault = str(track.default).lower() == "yes"
    title = str(track.title).lower()
    contains_sign_song = "sign" in title or "song" in title or "force" in title

    return (hasForced and not isDefault) or contains_sign_song


def replace_unknown_with_default(sub: SubFile):
    doc = sub._read_doc()
    new_events = []
    styles = doc.styles
    stylenames = [str(style.name) for style in styles]
    for line in doc.events:
        if str(line.style) not in stylenames and line.TYPE == "Dialogue":
            line.style = "Default"
        new_events.append(line)
    doc.events = new_events

    sub._update_doc(doc)
