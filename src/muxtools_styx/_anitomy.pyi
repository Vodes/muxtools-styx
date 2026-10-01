from enum import Enum

class ElementKind(Enum):
    AUDIO_TERM: ElementKind
    DEVICE: ElementKind
    EPISODE: ElementKind
    EPISODE_TITLE: ElementKind
    FILE_CHECKSUM: ElementKind
    FILE_EXTENSION: ElementKind
    LANGUAGE: ElementKind
    OTHER: ElementKind
    PART: ElementKind
    RELEASE_GROUP: ElementKind
    RELEASE_INFORMATION: ElementKind
    RELEASE_VERSION: ElementKind
    SEASON: ElementKind
    SOURCE: ElementKind
    SUBTITLES: ElementKind
    TITLE: ElementKind
    TYPE: ElementKind
    VIDEO_RESOLUTION: ElementKind
    VIDEO_TERM: ElementKind
    VOLUME: ElementKind
    YEAR: ElementKind
    EPISODE_ALTERNATIVE: ElementKind

class Element:
    def __init__(self, kind: ElementKind, value: str, position: int) -> None: ...
    @property
    def kind(self) -> ElementKind: ...
    @property
    def value(self) -> str: ...
    @property
    def position(self) -> int: ...

class Options:
    parse_episode: bool
    parse_episode_title: bool
    parse_file_checksum: bool
    parse_file_extension: bool
    parse_part: bool
    parse_release_group: bool
    parse_season: bool
    parse_title: bool
    parse_video_resolution: bool
    parse_year: bool

    def __init__(
        self,
        *,
        parse_episode: bool = True,
        parse_episode_title: bool = True,
        parse_file_checksum: bool = True,
        parse_file_extension: bool = True,
        parse_part: bool = True,
        parse_release_group: bool = True,
        parse_season: bool = True,
        parse_title: bool = True,
        parse_video_resolution: bool = True,
        parse_year: bool = True,
    ) -> None: ...

def parse(text: str, options: Options = ...) -> list[Element]: ...

__all__ = ["Element", "ElementKind", "Options", "parse"]
