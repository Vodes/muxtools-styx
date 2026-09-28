# muxtools-styx

`muxtools-styx` is a small, local-only policy layer for [muxtools](https://github.com/Jaded-Encoding-Thaumaturgy/muxtools). It can clean up one mux, combine a new target with selected tracks from a donor, inspect media and parsed filename metadata, or preflight and process an episode directory sequentially.

Python 3.12 or newer and MKVToolNix/FFmpeg are required. Binary wheels are published for Linux x86_64/ARM64, Windows x86_64/ARM64, and macOS ARM64.

## CLI

```console
muxtools-styx mux target.mkv -o finished.mkv
muxtools-styx mux target.mkv --donor previous.mkv --fill-audio --keep-subs-missing-languages
muxtools-styx batch downloads/ --donor-dir previous/ --out-dir muxed --dry-run
muxtools-styx --json inspect '[Group] Show - 03 [1080p CR].mkv'
```

The important source-policy flags are:

- `--keep-video`: use donor video instead of target video.
- `--keep-audio`: append every donor audio track.
- `--fill-audio`: append donor audio languages absent from the target, plus matching forced/sign tracks. It cannot be combined with `--keep-audio`.
- `--keep-subs`: append every donor subtitle.
- `--keep-subs-missing-languages`: append donor subtitle languages absent from the target.
- `--keep-non-english`: append non-English donor subtitles.
- `--discard-new-subs`: remove target subtitles before donor subtitle policy is applied.
- `--best-audio`: retain one Japanese candidate using the deliberately narrow web-audio preference documented in the source.
- `--remove-unnecessary`: retain only configured audio/subtitle languages.

`--audio-sync` and `--sub-sync` are independent donor offsets in milliseconds. `--restyle-subs` applies the Styx Gandhi-family cleanup to selected ASS tracks. `--fix-tags` repairs technical metadata and flags; `--normalize-track-names` separately normalizes user-facing audio/subtitle titles. `--tpp` is currently a documented no-op and emits one warning.

A donor-free `mux` using only `--fix-tags`, `--normalize-track-names`, or both edits an MKV in place with `mkvpropedit` when `-o` is omitted or points to the input file. Any other policy, or a distinct output path, uses the normal remux path.

`--supplemental-info TEXT` supplies extra target filename metadata for source provenance when the filename itself has no recognized service. `--donor-supplemental-info TEXT` does the same for a donor. A recognized source in the actual filename takes precedence.

Temporary muxtools work directories are removed after a successful mux. Pass `--no-clean-work-dirs` to retain extracted and transformed files for inspection.

In JSON mode normal diagnostics are written to stderr. Successful mux and batch results are stable, small objects suitable for Styx-Downloader:

```json
{"output":"/absolute/path/to/result.mkv"}
```

Styx-Downloader should resolve its own `%...%` metadata before invocation and may leave muxtools `$...$` tokens in `--out-name`.
The deferred `$crc32$` token is rejected because its final filename cannot be collision-checked during preflight.

## Python API

The caller owns the active `muxtools.Setup`; the operation owns inspection, selection, transformations, and the final mux.

```python
from pathlib import Path

from muxtools import Setup
from muxtools_styx import MuxOptions, TrackOptions, process_mux

Setup(
    episode="03",
    config_file="",
    show_name="Sousou no Frieren",
    out_dir="muxed",
    out_name="[Group] $show$ - $ep$ [$res$]",
)

output = process_mux(
    Path("target.mkv"),
    donor=Path("previous.mkv"),
    options=MuxOptions(tracks=TrackOptions(fill_audio=True, keep_subs_missing_languages=True)),
)
```

Batch matching uses normalized season/episode keys, applies offsets to the donor side, rejects duplicates and unsafe episode ranges, completes preflight before muxing, and runs accepted files sequentially because `muxtools.Setup` is process-wide state.

## Development

Clone with submodules, or initialize them before building:

```console
git submodule update --init --recursive
uv sync
uv run ruff format
uv run ruff check .
uv run pyrefly check
uv run pytest
uv build
```

Anitomy is a pinned Git submodule under `subprojects/anitomy` and is bound directly through nanobind. The binding preserves ordered elements, duplicates, UTF-8 values, and byte positions; Styx-specific interpretation remains in Python.
