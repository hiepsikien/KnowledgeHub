"""Reading-edition builder: family profile + labeled spans + REF/1 blocks."""

from .cache import load_cached_edition, save_cached_edition
from .pipeline import build_edition
from .profile import detect_family
from .ref import build_read_edition
from .ref_parser import assert_valid_edition, parse_manuscript_to_ref
from .ref_qa import parse_and_qa, qa_read_edition
from .ref_schema import BLOCK_TYPES, INLINE_STYLES, REF_FORMAT, validate_edition
from .spans import EditionSpan

__all__ = [
    "BLOCK_TYPES",
    "INLINE_STYLES",
    "EditionSpan",
    "REF_FORMAT",
    "assert_valid_edition",
    "build_edition",
    "build_read_edition",
    "detect_family",
    "load_cached_edition",
    "parse_manuscript_to_ref",
    "parse_and_qa",
    "qa_read_edition",
    "save_cached_edition",
    "validate_edition",
]
