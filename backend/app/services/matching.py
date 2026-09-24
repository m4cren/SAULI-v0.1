"""Auditable matching rules; the LLM cannot change time or availability rules."""

import math
import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher

from app.models.schemas import QueryAnalysis


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(character for character in value if not unicodedata.combining(character))
    return " ".join(re.findall(r"\w+", value))


def aware_utc(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timestamps must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def is_eligible(candidate: dict, last_seen_at: datetime) -> bool:
    return candidate["status"] == "available" and aware_utc(candidate["found_at"]) >= aware_utc(last_seen_at)


def text_similarity(left: str, right: str) -> float:
    left, right = normalize(left), normalize(right)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    first, second = set(left.split()), set(right.split())
    overlap = len(first & second) / len(first | second)
    fuzzy = SequenceMatcher(None, left, right, autojunk=False).ratio()
    return max(overlap, fuzzy * 0.8)


def list_similarity(query: list[str], candidate: list[str]) -> float:
    if not query or not candidate:
        return 0.0
    return sum(max(text_similarity(value, other) for other in candidate) for value in query) / len(query)


def nonempty(values):
    return [value for value in values if isinstance(value, str) and normalize(value) not in ("", "unknown", "none", "not assessable")]


def deterministic_features(query: QueryAnalysis, analysis: dict) -> float:
    groups = [
        (0.24, nonempty([query.generic_name, *query.possible_names]), nonempty([analysis.get("generic_name"), analysis.get("object_name"), *analysis.get("alternative_names", [])])),
        (0.08, nonempty([query.category, query.subcategory]), nonempty([analysis.get("category"), analysis.get("subcategory")])),
        (0.15, nonempty([query.brand]), nonempty([analysis.get("brand")])),
        (0.12, query.colors, analysis.get("colors", [])),
        (0.07, query.materials, analysis.get("material", [])),
        (0.10, query.visible_markings, analysis.get("visible_markings", [])),
        (0.10, query.distinctive_features, analysis.get("distinctive_features", [])),
        (0.07, query.damage_or_condition, nonempty([analysis.get("condition"), *analysis.get("condition_details", [])])),
        (
            0.07,
            query.component_details,
            nonempty(analysis.get("functional_components", [])),
        ),
    ]
    supplied = [(weight, source, target) for weight, source, target in groups if source]
    if not supplied:
        return 0.0
    return sum(weight * list_similarity(source, target) for weight, source, target in supplied) / sum(weight for weight, _, _ in supplied)


def location_similarity(last_seen_location: str, found_location: str) -> float:
    # A weak location match reduces ranking; it never excludes an item.
    stopwords = {"lspu", "university", "campus", "the", "at", "near", "in"}
    first = " ".join(word for word in normalize(last_seen_location).split() if word not in stopwords)
    second = " ".join(word for word in normalize(found_location).split() if word not in stopwords)
    return text_similarity(first, second)


def time_proximity(found_at: datetime | str, last_seen_at: datetime) -> float:
    seconds = (aware_utc(found_at) - aware_utc(last_seen_at)).total_seconds()
    if seconds < 0:
        return 0.0
    # Seven days halves this contribution, without imposing an additional cutoff.
    return 1.0 / (1.0 + seconds / (7 * 24 * 60 * 60))


def final_score(ai: float, features: float, location: float, time: float) -> float:
    components = [ai, features, location, time]
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in components):
        raise ValueError("Score components must be finite values from zero to one")
    return 100 * (ai * 0.55 + features * 0.20 + location * 0.15 + time * 0.10)


def rank_matches(matches: list[dict]) -> list[dict]:
    return sorted(matches, key=lambda result: (-result["final_score"], str(result["found_item_id"])))
