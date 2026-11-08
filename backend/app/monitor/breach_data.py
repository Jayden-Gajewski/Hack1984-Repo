"""Reference data for the threat monitor: data/breach_data_classes.json, loaded once."""

from functools import lru_cache
from typing import Any

from app.data import load_json
from app.models import FIELD_TYPES

TIERS = ("low", "medium", "high", "critical")  # weakest first, so index() compares


@lru_cache
def _data() -> dict[str, Any]:
    return load_json("breach_data_classes.json")


def category(key: str) -> dict[str, Any]:
    return _data()["categories"][key]


def tier(key: str) -> str:
    return category(key)["tier"]


def label(key: str) -> str:
    return category(key)["label"]


def action(key: str) -> dict[str, Any]:
    return _data()["actions"][key]


def sort_categories(keys: list[str]) -> list[str]:
    """Unique known categories, most severe first; order within a tier is kept. Unknown keys
    (from an older version of the data file) are dropped rather than crashing."""
    known = _data()["categories"]
    unique = [k for k in dict.fromkeys(keys) if k in known]
    return sorted(unique, key=lambda k: -TIERS.index(tier(k)))


def category_of(data_class: str) -> str:
    """The category for one of HIBP's data class names ("Email addresses" -> "email")."""
    data = _data()
    return data["data_classes"].get(data_class.strip().lower(), data["default_category"])


def categories_for_classes(data_classes: list[str]) -> list[str]:
    return sort_categories([category_of(c) for c in data_classes])


def categories_for_fields(fields: list[str]) -> list[str]:
    """Categories for Stage 3's data types (models.FIELD_TYPES), e.g. "ssn" -> "government_id"."""
    mapping = _data()["field_types"]
    return sort_categories([mapping[f] for f in fields if f in mapping and not f.startswith("_")])


def field_types_for(categories: list[str]) -> list[str]:
    """The listing vocabulary (models.FIELD_TYPES) for these categories, in that order."""
    fields = {category(c)["field"] for c in categories} - {None}
    return [f for f in FIELD_TYPES if f in fields]


def sentence_label(key: str) -> str:
    """The label for use mid-sentence: "Passwords" -> "passwords", "Government ID numbers"
    -> "government ID numbers" (an acronym keeps its capitals)."""
    text = label(key)
    if len(text) > 1 and text[1].islower():
        return text[0].lower() + text[1:]
    return text
