"""Reading-edition builder: family profile + labeled spans. Raw files stay untouched."""

from .pipeline import build_edition
from .profile import detect_family
from .spans import EditionSpan

__all__ = ["EditionSpan", "build_edition", "detect_family"]
