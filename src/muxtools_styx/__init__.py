from .batch import BatchMatch, BatchPreflight, BatchResult, preflight_batch, process_batch
from .cli import main
from .mux import process_mux
from .selection import MuxOptions, SyncOptions, TrackOptions, TransformOptions

__version__: str
__version_tuple__: tuple[int | str, ...]

try:
    from ._version import __version__, __version_tuple__
except ImportError:
    __version__ = "0.0.0+unknown"
    __version_tuple__ = (0, 0, 0, "+unknown")

__all__ = [
    "BatchMatch",
    "BatchPreflight",
    "BatchResult",
    "MuxOptions",
    "SyncOptions",
    "TrackOptions",
    "TransformOptions",
    "main",
    "preflight_batch",
    "process_batch",
    "process_mux",
]
