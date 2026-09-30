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


def test_truncated_root_is_not_mistaken_for_nested_component():
    with pytest.raises(ValueError, match="Incomplete top-level"):
        first_json_object('{"component_counts":[{"component":"phone","count":1}')


def test_empty_analysis_and_extra_reasoning_are_not_accepted():
    with pytest.raises(ValidationError):
        FoundItemAnalysis.model_validate({})
    with pytest.raises(ValidationError):
        FoundItemAnalysis(generic_name="wallet", object_name="wallet", chain_of_thought="private")


def test_sensitive_document_attributes_are_discarded():
    original = FoundItemAnalysis(generic_name="identification card", object_name="Student identification card", visible_markings=["private details"], extraction_summary="private details")
    protected = protect_document_analysis(original)
    assert protected.object_name == "school ID"
    assert protected.visible_markings == []
    assert "private details" not in protected.model_dump_json()


def test_id_retains_only_document_type_and_plausible_printed_name():
    original = FoundItemAnalysis(
        generic_name="school ID",
        object_name="school ID 123456789",
        document_kind="school ID",
        document_owner_name="Juan Dela Cruz",
        visible_markings=["Student number 123456789"],
        extraction_summary="Phone 09123456789; address 10 Main Street",
    )
    protected = protect_document_analysis(original)
    assert protected.extraction_summary == "school ID for Juan Dela Cruz."
    assert protected.document_owner_name == "Juan Dela Cruz"
    assert protected.visible_markings == []
    assert "123456789" not in protected.model_dump_json()

    unsafe = original.model_copy(update={"document_owner_name": "Juan 123456789"})
    assert protect_document_analysis(unsafe).document_owner_name is None
    comma_with_number = original.model_copy(
        update={"document_owner_name": "Dela Cruz, Juan 123456789"}
    )
    assert protect_document_analysis(comma_with_number).document_owner_name is None


def test_wallet_with_id_keeps_wallet_identity_but_discards_private_card_text():
    original = FoundItemAnalysis(
        generic_name="wallet",
        object_name="black leather wallet with an identification card 123456789",
        document_kind="identification card",
        document_owner_name="Cruz, Maria Elena",
        colors=["black", "blue"],
        visible_markings=["ID number 123456789"],
        short_description="Address 10 Main Street",
        extraction_summary="Phone 09123456789 and ID number 123456789",
    )

    protected = protect_document_analysis(original)

    assert protected.generic_name == "wallet"
    assert protected.object_name == "Black leather wallet"
    assert protected.colors == ["black"]
    assert protected.document_kind == "identification card"
    assert protected.document_owner_name is None
    assert protected.extraction_summary == (
        "Black leather wallet containing an identification card."
    )
    assert protected.visible_markings == []
    assert "123456789" not in protected.model_dump_json()
    assert "Main Street" not in protected.model_dump_json()
    assert protect_document_analysis(protected).model_dump() == protected.model_dump()


def test_id_card_in_wallet_is_not_reduced_to_loose_id():
    original = FoundItemAnalysis(
        generic_name="identification card",
        object_name="black wallet containing a school ID",
        document_kind="school ID",
        extraction_summary="school ID with private contents",
    )
    protected = protect_document_analysis(original)
    assert protected.generic_name == "wallet"
    assert protected.extraction_summary == "Black wallet containing a school ID."
    assert protected.document_kind == "school ID"


def test_wallet_normalizer_rejects_a_name_in_a_forged_rich_summary():
    original = FoundItemAnalysis(
        generic_name="wallet",
        object_name="black wallet",
        document_kind="school ID",
        extraction_summary=(
            "Black folding wallet with card slots and Kyle Adrien printed "
            "on a card. It contains a school ID."
        ),
    )
    protected = protect_document_analysis(original)
    assert protected.extraction_summary == "Black wallet containing a school ID."
    assert "Kyle" not in protected.model_dump_json()


def test_ordinary_wallet_without_document_is_unchanged():
    original = FoundItemAnalysis(
        generic_name="wallet",
        object_name="black leather wallet",
        colors=["black"],
        extraction_summary="Black leather wallet with worn corners.",
    )
    assert protect_document_analysis(original) is original


def test_document_protection_does_not_fabricate_an_ordinary_wallet_summary():
    original = FoundItemAnalysis(
        generic_name="wallet",
        object_name="black long wallet",
        colors=["black"],
        short_description="",
        extraction_summary="",
    )
    result = protect_document_analysis(original)
    assert result is original
    assert result.extraction_summary == ""


def test_document_protection_does_not_copy_card_text_into_an_empty_summary():
    original = FoundItemAnalysis(
        generic_name="wallet",
        object_name="black wallet",
        short_description="Card 123456789",
        extraction_summary="",
    )
    result = protect_document_analysis(original)
    assert result.extraction_summary == ""
    assert "123456789" not in result.extraction_summary


def test_upload_rejects_declared_type_spoofing(png):
    with pytest.raises(Exception, match="does not match"):
        validate_image(png, "image/jpeg")


def test_upload_rejects_oversized_data():
    with pytest.raises(Exception, match="10 MiB"):
        validate_image(b"x" * (MAX_IMAGE_BYTES + 1), "image/png")
