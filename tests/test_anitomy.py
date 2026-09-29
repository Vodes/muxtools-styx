from __future__ import annotations

import pytest

from muxtools_styx import _anitomy


def test_all_upstream_element_kinds_are_exposed() -> None:
    assert {kind.name for kind in _anitomy.ElementKind} == {
        "AUDIO_TERM",
        "DEVICE",
        "EPISODE",
        "EPISODE_TITLE",
        "FILE_CHECKSUM",
        "FILE_EXTENSION",
        "LANGUAGE",
        "OTHER",
        "PART",
        "RELEASE_GROUP",
        "RELEASE_INFORMATION",
        "RELEASE_VERSION",
        "SEASON",
        "SOURCE",
        "SUBTITLES",
        "TITLE",
        "TYPE",
        "VIDEO_RESOLUTION",
        "VIDEO_TERM",
        "VOLUME",
        "YEAR",
    }
    assert not hasattr(_anitomy, "TITLE")


def test_parse_preserves_order_unicode_byte_positions_and_nulls() -> None:
    elements = _anitomy.parse("[G] Café\0 - 01 [CR].mkv")
    assert [element.position for element in elements] == sorted(element.position for element in elements)
    title = next(element for element in elements if element.kind is _anitomy.ElementKind.TITLE)
    episode = next(element for element in elements if element.kind is _anitomy.ElementKind.EPISODE)
    assert title.value == "Café\0"
    assert episode.position == len("[G] Café\0 - ".encode())


def test_options_expose_all_ten_switches() -> None:
    options = _anitomy.Options(parse_title=False, parse_episode=False)
    assert not options.parse_title
    assert not options.parse_episode
    assert len(_anitomy.parse("Show - 01.mkv", options)) < len(_anitomy.parse("Show - 01.mkv"))


def test_element_is_immutable() -> None:
    element = _anitomy.Element(_anitomy.ElementKind.TITLE, "Show", 0)
    attribute = "value"
    with pytest.raises(AttributeError):
        setattr(element, attribute, "Other")


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("", []),
        ("Show", [("TITLE", "Show", 0)]),
        ("Show.mkv", [("TITLE", "Show", 0), ("FILE_EXTENSION", "mkv", 5)]),
        ("Show - 07.5.mkv", [("TITLE", "Show", 0), ("EPISODE", "07.5", 7), ("FILE_EXTENSION", "mkv", 12)]),
        ("Show 4a.mkv", [("TITLE", "Show", 0), ("EPISODE", "4a", 5), ("FILE_EXTENSION", "mkv", 8)]),
        (
            "NieR:Automata Ver1.1a - 03.mkv",
            [("TITLE", "NieR:Automata Ver1.1a", 0), ("EPISODE", "03", 24), ("FILE_EXTENSION", "mkv", 27)],
        ),
        (
            "Show 2nd Season - 02.mkv",
            [("TITLE", "Show", 0), ("SEASON", "2", 5), ("EPISODE", "02", 18), ("FILE_EXTENSION", "mkv", 21)],
        ),
        (
            "[Group] Show Season 2 - 07.5 [2020].mkv",
            [
                ("RELEASE_GROUP", "Group", 1),
                ("TITLE", "Show", 8),
                ("SEASON", "2", 20),
                ("EPISODE", "07.5", 24),
                ("YEAR", "2020", 30),
                ("FILE_EXTENSION", "mkv", 36),
            ],
        ),
    ],
)
def test_parser_compatibility(filename: str, expected: list[tuple[str, str, int]]) -> None:
    assert [(element.kind.name, element.value, element.position) for element in _anitomy.parse(filename)] == expected
