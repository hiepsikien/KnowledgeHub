"""Read publisher options — keep in sync with Read apps/api categories + chapters."""

from __future__ import annotations

# Read apps/api/app/categories.py CATEGORY_SEED
READ_CATEGORIES: list[tuple[str, str]] = [
    ("fiction", "Fiction"),
    ("romance", "Romance"),
    ("fantasy", "Fantasy"),
    ("science-fiction", "Science Fiction"),
    ("mystery-thriller", "Mystery & Thriller"),
    ("horror", "Horror"),
    ("historical-fiction", "Historical Fiction"),
    ("literary-fiction", "Literary Fiction"),
    ("young-adult", "Young Adult"),
    ("poetry", "Poetry"),
    ("essays", "Essays"),
    ("memoir-biography", "Memoir & Biography"),
    ("self-help", "Self-Help"),
    ("business", "Business"),
    ("other", "Other"),
]

# Read packages/api-client SPLIT_LENGTH_OPTIONS + apps/api/app/chapters.py SPLIT_PROFILES
SPLIT_LENGTH_OPTIONS: list[dict[str, str | int]] = [
    {
        "value": "short",
        "label": "Short",
        "hint": "~5–8 min",
        "target_words": 900,
        "max_words": 1400,
        "min_words": 350,
    },
    {
        "value": "standard",
        "label": "Standard",
        "hint": "~10–15 min",
        "target_words": 2000,
        "max_words": 3000,
        "min_words": 650,
    },
    {
        "value": "long",
        "label": "Long",
        "hint": "~20–25 min",
        "target_words": 3500,
        "max_words": 5000,
        "min_words": 1200,
    },
]

SPLIT_LENGTHS = {str(row["value"]) for row in SPLIT_LENGTH_OPTIONS}
CATEGORY_SLUGS = {slug for slug, _ in READ_CATEGORIES}


def read_publisher_options() -> dict:
    return {
        "categories": [{"slug": slug, "label": label} for slug, label in READ_CATEGORIES],
        "split_lengths": SPLIT_LENGTH_OPTIONS,
        "status": "pending_review",
        "split_note": (
            "Read detects chapters/sections then packs them into reading segments "
            "without cutting a section across two units."
        ),
    }


def validate_split_length(value: str) -> str:
    key = (value or "standard").strip()
    if key not in SPLIT_LENGTHS:
        raise ValueError(f"split_length must be one of {sorted(SPLIT_LENGTHS)}")
    return key


def validate_category_slug(value: str) -> str:
    slug = (value or "essays").strip()
    if slug not in CATEGORY_SLUGS:
        raise ValueError(f"unknown Read category: {slug}")
    return slug
