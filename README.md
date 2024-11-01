# muxtools-styx
Commandline Tool for the [Styx backend/downloader](https://github.com/Vodes/Styx-Downloader) using [muxtools](https://github.com/Jaded-Encoding-Thaumaturgy/muxtools).

## Usage

```
usage: muxtools-styx [-h] --output OUTPUT [--verbose] [--keep-video] [--keep-audio] [--best-audio] [--audio-sync AUDIO_SYNC] [--sub-sync SUB_SYNC] [--discard-new-subs]
                     [--keep-subs] [--keep-non-english] [--sushi-subs] [--tpp-subs] [--tpp-styles TPP_STYLES] [--restyle-subs] [--fix-tagging]
                     [--sub-languages SUB_LANGUAGES]
                     input [input ...]

Random CLI Tool based on muxtools used for the Styx backend.

positional arguments:
  input                 Input files to be processed. (Max 2)

options:
  -h, --help            show this help message and exit
  --output OUTPUT, -o OUTPUT
                        Path for the file that will be output
  --verbose, -v         Enable output of mkvmerge and other tools
  --keep-video, -kv     Keep video track of first input
  --keep-audio, -ka     Keep audio tracks of first input
  --best-audio, -ba     Automatically determine best japanese audio of both inputs and keep that
  --audio-sync AUDIO_SYNC, -as AUDIO_SYNC
                        Delay to apply to audio tracks from first input in ms
  --sub-sync SUB_SYNC, -ss SUB_SYNC
                        Delay to apply to subtitle tracks from first input in ms
  --discard-new-subs, -discardsubs
                        Discard subtitle tracks of the second input
  --keep-subs, -ks      Keep subtitle tracks of first input
  --keep-non-english, -kne
                        Keep non-english subtitle tracks of first input
  --sushi-subs, -sushi  Automatically sync subtitles via sushi
  --tpp-subs, -tpp      Apply timing post processor to subtitles
  --tpp-styles TPP_STYLES, -styles TPP_STYLES
                        Styles to apply the TPP to
  --restyle-subs, -restyle
                        Restyle subtitles to the cabin preset
  --fix-tagging, -ft    Attempt to automatically fix tagging issues
  --sub-languages SUB_LANGUAGES, -sl SUB_LANGUAGES
                        Languages to apply tpp and/or restyling to. Defaults to ['de', 'en']
```