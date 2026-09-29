from collections.abc import Mapping
from typing import Any

from versioningit import get_version


def dynamic_metadata(settings: Mapping[str, Any], project: Mapping[str, Any]) -> dict[str, str]:
    return {"version": get_version(write=True)}
