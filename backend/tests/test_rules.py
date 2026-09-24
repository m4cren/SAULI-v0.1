import math
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.models.schemas import FoundItemAnalysis, MatchAssessment, QueryAnalysis, SearchInput
from app.services.ai import first_json_object, protect_document_analysis
from app.services.images import MAX_IMAGE_BYTES, validate_image
from app.services.matching import aware_utc, deterministic_features, final_score, is_eligible, rank_matches
from conftest import FOUND_AT, ITEM_ID, analysis, item

SESSION_ID = "00000000-0000-4000-8000-000000000010"
IDEMPOTENCY_ID = "00000000-0000-4000-8000-000000000020"


def test_ollama_bind_address_is_normalized_for_client_use():
    assert Settings(ollama_host="0.0.0.0:11434").ollama_host == "http://127.0.0.1:11434"


@pytest.mark.parametrize("minutes,expected", [(-1, True), (0, True), (1, False)])
def test_hard_temporal_boundary(minutes, expected):
    assert is_eligible(item(), FOUND_AT + timedelta(minutes=minutes)) is expected


def test_retrieved_items_are_never_eligible():
    assert not is_eligible(item(status="retrieved"), FOUND_AT - timedelta(days=1))


def test_timezone_offsets_are_compared_as_instants():
    assert is_eligible(item(), datetime(2026, 9, 23, 20, 0, tzinfo=timezone(timedelta(hours=8))))


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        aware_utc("2026-09-23T12:00:00")
    with pytest.raises(ValidationError):
        SearchInput(
            description="wallet",
            last_seen_location="Library",
            last_seen_at="2026-09-23T12:00:00",
            anonymous_session_id=SESSION_ID,
            idempotency_key=IDEMPOTENCY_ID,
        )


@pytest.mark.parametrize("value,expected", [(-0.4, 0.0), (1.6, 1.0), (0.75, 0.75), (1, 1.0)])
def test_ai_scores_are_clamped(value, expected):
    assert MatchAssessment(candidate_id=ITEM_ID, ai_similarity=value).ai_similarity == expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "0.5", True, None])
def test_invalid_ai_scores_are_rejected(value):
    with pytest.raises(ValidationError):
        MatchAssessment(candidate_id=ITEM_ID, ai_similarity=value)


def test_final_score_uses_exact_documented_weights():
    assert final_score(0.8, 0.6, 0.4, 0.2) == pytest.approx(64)
    with pytest.raises(ValueError):
        final_score(math.nan, 1, 1, 1)


def test_equal_scores_have_stable_id_tiebreaker():
    rows = [{"found_item_id": "b", "final_score": 75}, {"found_item_id": "a", "final_score": 75}]
    assert rank_matches(rows) == rank_matches(list(reversed(rows)))
    assert rank_matches(rows)[0]["found_item_id"] == "a"


def test_features_use_available_query_evidence():
    query = QueryAnalysis(generic_name="wallet", colors=["black"])
    correct = deterministic_features(query, analysis().model_dump())
    unrelated = deterministic_features(query, {"generic_name": "umbrella", "object_name": "red umbrella", "colors": ["red"]})
    assert correct > unrelated
    assert 0 <= unrelated <= correct <= 1


def test_json_extraction_handles_fences_trailing_text_nested_and_quoted_braces():
    assert first_json_object('before ```json\n{"a":{"b":"} is quoted"}}\n``` after {broken') == {"a": {"b": "} is quoted"}}


def test_empty_analysis_and_extra_reasoning_are_not_accepted():
    with pytest.raises(ValidationError):
        FoundItemAnalysis.model_validate({})
    with pytest.raises(ValidationError):
        FoundItemAnalysis(generic_name="wallet", object_name="wallet", chain_of_thought="private")


def test_sensitive_document_attributes_are_discarded():
    original = FoundItemAnalysis(generic_name="identification card", object_name="Student identification card", visible_markings=["private details"], extraction_summary="private details")
    protected = protect_document_analysis(original)
    assert protected.object_name == "identification card"
    assert protected.visible_markings == []
    assert "private details" not in protected.model_dump_json()


def test_upload_rejects_declared_type_spoofing(png):
    with pytest.raises(Exception, match="does not match"):
        validate_image(png, "image/jpeg")


def test_upload_rejects_oversized_data():
    with pytest.raises(Exception, match="10 MiB"):
        validate_image(b"x" * (MAX_IMAGE_BYTES + 1), "image/png")
