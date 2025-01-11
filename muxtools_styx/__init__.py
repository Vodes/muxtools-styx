import time
from argparse import ArgumentParser
from pathlib import Path
from muxtools import error

from .internals import basic_mux, advanced_mux, fix_tags, set_mkv_title

parser = ArgumentParser("muxtools-styx", description="Random CLI Tool based on muxtools used for the Styx backend.")
parser.add_argument("--output", "-o", type=lambda st: Path(st).resolve(), required=True, help="Path for the file that will be output")
parser.add_argument("--verbose", "-v", action="store_true", help="Enable output of mkvmerge and other tools")

parser.add_argument("--keep-video", "-kv", action="store_true", help="Keep video track of first input")
parser.add_argument(
    "--keep-audio", "-ka", action="store_true", help="Keep audio tracks of first input if the second one doesn't have the language yet."
)
parser.add_argument("--best-audio", "-ba", action="store_true", help="Automatically determine best japanese audio of both inputs and keep that")
parser.add_argument("--audio-sync", "-as", type=int, help="Delay to apply to audio tracks from first input in ms")
parser.add_argument("--sub-sync", "-ss", type=int, help="Delay to apply to subtitle tracks from first input in ms")
parser.add_argument("--discard-new-subs", "-discardsubs", action="store_true", help="Discard subtitle tracks of the second input")
parser.add_argument("--keep-subs", "-ks", action="store_true", help="Keep subtitle tracks of first input")
parser.add_argument("--keep-non-english", "-kne", action="store_true", help="Keep non-english subtitle tracks of first input")
parser.add_argument("--sushi-subs", "-sushi", action="store_true", help="Automatically sync subtitles via sushi")
parser.add_argument("--tpp-subs", "-tpp", action="store_true", help="Apply timing post processor to subtitles")
parser.add_argument("--tpp-styles", "-styles", type=str, default="default,main,alt,flashback,top,italic", help="Styles to apply the TPP to")
parser.add_argument("--restyle-subs", "-restyle", action="store_true", help="Restyle subtitles to the gandhi preset")
parser.add_argument("--fix-tagging", "-ft", action="store_true", help="Attempt to automatically fix tagging issues")
parser.add_argument(
    "--mkv-title",
    "-t",
    type=str,
    help="Set mkv title of the resulting output to this. Definitely recommended to set one because muxtools has useless defaults.",
)

parser.add_argument(
    "--remove-unnecessary", "-rm", action="store_true", help="Remove all audio and subtitle tracks that are not specified with the -al or -sl params."
)

parser.add_argument(
    "--audio-languages",
    "-al",
    action="append",
    type=str,
    default=[],
    help="Languages to keep if removing unnecessary. Defaults to ['de', 'en', 'ja']",
)

parser.add_argument(
    "--sub-languages",
    "-sl",
    action="append",
    type=str,
    default=[],
    help="Languages to keep if removing or apply tpp and/or restyling to. Defaults to ['de', 'en']",
)

parser.add_argument("input", type=lambda st: Path(st).resolve(), nargs="+", help="Input files to be processed. (Max 2)")


def main():
    args = parser.parse_args()
    if not args.sub_languages:
        args.sub_languages = ["de", "en"]

    if not args.audio_languages:
        args.audio_languages = ["de", "en", "ja"]

    if (
        any([args.keep_video, args.keep_audio, args.audio_sync, args.sub_sync, args.discard_new_subs, args.keep_subs, args.keep_non_english])
        and len(args.input) < 2
    ):
        error("You need atleast 2 inputs for these options!")
        exit(1)

    if not any([args.best_audio, args.sushi_subs, args.tpp_subs, args.restyle_subs, args.remove_unnecessary]) and len(args.input) > 1:
        muxed = basic_mux(args.input[0], args.input[1], args, args.output)
    elif len(args.input) == 1:
        if any([args.tpp_subs, args.sushi_subs, args.restyle_subs, args.remove_unnecessary]):
            muxed = advanced_mux(args.input[0], args)
        else:
            muxed = args.input[0]
    else:
        output = Path(args.output)
        premuxed = basic_mux(args.input[0], args.input[1], args, Path(f"{output.stem}.temp{output.suffix}"))
        time.sleep(2)
        muxed = advanced_mux(premuxed, args, args.input[0])
        premuxed.unlink(True)

    if args.fix_tagging:
        fix_tags(muxed)

    if args.mkv_title:
        set_mkv_title(muxed, args.mkv_title)

    print(f"Output: {muxed.resolve()}")
