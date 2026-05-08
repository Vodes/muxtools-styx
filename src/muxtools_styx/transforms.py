from __future__ import annotations

from muxtools import GJM_GANDHI_PRESET, FontFile, SubFile, edit_style, gandhi_default

from .models import SubtitleTransform


def build_subtitle_transforms(transforms: list[SubtitleTransform]) -> tuple[list[object], list[FontFile]]:
    transformed_tracks = list[object]()
    font_attachments = list[FontFile]()

    for transform in transforms:
        if transform.kind != "restyle":
            continue

        # mkvextract already yields subtitle files with effective timestamps applied,
        # so preserving the original container delay here would shift the track twice on remux.
        sub = SubFile.from_mkv(transform.source, transform.relative_index, preserve_delay=False)
        preset = GJM_GANDHI_PRESET.copy()
        preset.append(edit_style(gandhi_default, "Sign"))
        preset.append(edit_style(gandhi_default, "Subtitle"))
        preset.append(edit_style(gandhi_default, "Subtitle-3", fontsize=66))
        sub = sub.unfuck_cr(
            alt_styles=["overlap", "subtitle-2"],
            dialogue_styles=["main", "default", "narrator", "narration", "subtitle", "bd dx"],
        ).purge_macrons().restyle(preset)
        font_attachments.extend(sub.collect_fonts(search_current_dir=False))
        transformed_tracks.append(
            sub.to_track(
                transform.title or "",
                transform.language or "en",
                transform.is_default,
                transform.is_forced,
            )
        )

    return transformed_tracks, font_attachments
