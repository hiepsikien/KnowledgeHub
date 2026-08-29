"""Reading-edition builder: family profile + labeled spans + REF/1 blocks."""

from .cache import load_cached_edition, save_cached_edition
from .pipeline import build_edition
from .profile import detect_family
from .ref import build_read_edition
from .serialize import REF_FORMAT
from .spans import EditionSpan

__all__ = [
    "EditionSpan",
    "REF_FORMAT",
    "build_edition",
    "build_read_edition",
    "detect_family",
    "load_cached_edition",
    "save_cached_edition",
]
